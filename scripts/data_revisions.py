"""완전한 공개 집계 사이의 변경만 기록한다. 개별 거래나 변경 원인은 추정하지 않는다."""
import copy
import datetime as dt
import gzip
import json
import math
from pathlib import Path

EVENT_LIMIT = 12
CHANGE_LIMIT = 20000
TYPE_NAMES = {'apt': '아파트', 'rh': '연립·다세대', 'offi': '오피스텔'}
FIELDS = {
    'moveins': [('scheduled', '입주예정(월 기재)', '호')],
    'pipeline': [('permit', '아파트 인허가', '호'), ('start', '아파트 착공', '호'), ('completion', '아파트 준공', '호')],
    'supply': [('total', '전체 미분양', '호'), ('completed', '준공 후 미분양', '호')],
    'rents': [('n', '전월세 계약', '건'), ('jeonse_n', '전세 계약', '건'),
              ('monthly_n', '월세 계약', '건'), ('deposit', '전세 중위 보증금', '만원'),
              ('rent', '월세 중위액', '만원/월'), ('new_n', '신규 계약', '건'),
              ('renewal_n', '갱신 계약', '건'), ('unknown_n', '유형 미확인 계약', '건')],
    'trades': [('n', '매매 거래', '건'), ('price', '매매 중위가격', '만원')],
}


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def complete(kind, data):
    if not isinstance(data, dict) or data.get('failed') or not isinstance(data.get('months'), list) or not isinstance(data.get('collected'), str):
        return False
    groups = data.get('agg', {}) if kind == 'trades' else {'all': data.get('values', {})}
    if not isinstance(groups, dict) or not groups:
        return False
    for regions in groups.values():
        if not isinstance(regions, dict) or not regions:
            return False
        for series in regions.values():
            if not isinstance(series, dict):
                return False
            if kind in ('trades', 'rents'):
                counts = series.get('n', [])
                if len(counts) != len(data['months']) or any(not finite(v) or v < 0 for v in counts):
                    return False
    return True


def compatible(kind, a, b):
    if not complete(kind, a) or not complete(kind, b):
        return False
    keys = ('analysis_version', 'min_price_sample') if kind == 'trades' else ('schema_version', 'min_sample')
    return all(a.get(k) == b.get(k) for k in keys)


def cells(kind, data):
    """공개 월별 지표만 추출하고 소표본 가격은 제외한다."""
    groups = data.get('agg', {}) if kind == 'trades' else {'': data.get('values', {})}
    result = {}
    for category, regions in groups.items():
        for region, series in regions.items():
            for field, label, unit in FIELDS[kind]:
                for i, value in enumerate(series.get(field, [])):
                    if i >= len(data['months']):
                        break
                    if kind == 'trades' and field == 'price':
                        samples = series.get('price_n', [])
                        if i >= len(samples) or not finite(samples[i]) or samples[i] < data.get('min_price_sample', 10):
                            value = None
                    result[(region, data['months'][i], category, field)] = (value if finite(value) else None, label, unit)
            if kind == 'moveins':
                for year in {m[:4] for m in data['months']}:
                    value = series.get('unscheduled', {}).get(year, 0) if series.get('district_available', True) else None
                    result[(region, year + '-00', category, 'unscheduled')] = (value, '입주예정(월 미정)', '호')
    return result


def changes(kind, before, after):
    old, new = cells(kind, before), cells(kind, after)
    result = []
    # 새 월·새 지역·기간에서 사라진 월은 수정으로 세지 않는다.
    for key in sorted(old.keys() & new.keys(), key=lambda k: (k[1], k[0], k[2], k[3]), reverse=True):
        a, label, unit = old[key]
        b = new[key][0]
        if a == b:
            continue
        region, month, category, field = key
        result.append({'region': region, 'month': month, 'category': TYPE_NAMES.get(category, ''),
                       'metric': label, 'unit': unit, 'before': a, 'after': b,
                       'delta': round(b - a, 2) if a is not None and b is not None else None,
                       'status': '자료 보완' if a is None else '표시 보류' if b is None else '수치 변경'})
    return result


def baseline(kind, paths, data):
    candidates = []
    for path in paths:
        if not path or not Path(path).exists():
            continue
        try:
            with gzip.open(path, 'rt', encoding='utf-8') as f:
                old = json.load(f)
            if compatible(kind, old, data) and old.get('collected'):
                candidates.append(old)
        except (OSError, ValueError):
            print(f'{kind}: 읽을 수 없는 이전 집계를 비교에서 제외합니다')
    return max(candidates, key=lambda d: (d['collected'], bool(d.get('revision_history')))) if candidates else None


def history(kind, data, previous=None, observed_at=None):
    if not complete(kind, data):
        raise ValueError('불완전한 수집은 게시용 변경 이력에 기록하지 않습니다')
    if previous and previous.get('collected', '') > data['collected']:
        raise ValueError('이전 자료보다 오래된 집계로 게시 자료를 덮어쓸 수 없습니다')
    stamp = observed_at or dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime('%Y-%m-%d %H:%M KST')
    can_compare = previous is not None and compatible(kind, previous, data)
    stored = previous.get('revision_history', {}) if can_compare else {}
    result = copy.deepcopy(stored) if stored.get('schema_version') == 1 else {
        'schema_version': 1, 'tracking_since': stamp, 'events': [],
        'dropped_events': 0, 'dropped_changes': 0,
    }
    result.update(kind=kind, last_collected=data['collected'], last_checked=stamp,
                  event_limit=EVENT_LIMIT, change_limit=CHANGE_LIMIT)
    updated = changes(kind, previous, data) if can_compare else []
    if updated:
        result['events'].append({'before_collected': previous['collected'], 'after_collected': data['collected'],
                                 'observed_at': stamp, 'change_count': len(updated), 'changes': updated})
    while len(result['events']) > EVENT_LIMIT:
        removed = result['events'].pop(0)
        result['dropped_events'] += 1
        result['dropped_changes'] += len(removed['changes'])
    remaining = CHANGE_LIMIT
    for event in reversed(result['events']):
        keep = min(remaining, len(event['changes']))
        result['dropped_changes'] += len(event['changes']) - keep
        event['changes'] = event['changes'][:keep]
        remaining -= keep
    return result


def save_published(kind, data, path, seed=None):
    path = Path(path)
    old = baseline(kind, (path, seed), data)
    data['revision_history'] = history(kind, data, old)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix('.part')
    part.write_bytes(gzip.compress(json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode(), mtime=0))
    part.replace(path)
