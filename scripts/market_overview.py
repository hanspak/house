"""지역별 가격·거래·임대차·공급·구매부담을 공통 형식으로 묶는다."""
import datetime as dt
import gzip
import hashlib
import json
import math
import os
from pathlib import Path

from trade_regions import PROVINCES, KB_NAMES, districts
from housing_moveins import shift
from data_health import report, kst_today

ROOT = Path(__file__).resolve().parents[1]


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def metric(value=None, unit='', period=None, scope=None, note=''):
    return {'value': round(value, 2) if finite(value) else None, 'unit': unit,
            'period': period, 'scope': scope, 'note': note}


def latest(values, dates):
    for i in range(min(len(values or []), len(dates)) - 1, -1, -1):
        if finite(values[i]):
            return values[i], dates[i]
    return None, None


def weekly_change(values, dates):
    end_value, end_date = latest(values, dates)
    if end_date is None:
        return None, None
    target = dt.date.fromisoformat(end_date) - dt.timedelta(days=28)
    for i in range(min(len(values), len(dates)) - 1, -1, -1):
        date = dt.date.fromisoformat(dates[i])
        if date <= target and 0 <= (target - date).days <= 7 and finite(values[i]) and values[i] > 0:
            return (end_value / values[i] - 1) * 100, dates[i] + '~' + end_date
    return None, end_date


def kb_scope(region, values):
    province, _, district = region.partition('|')
    parent = '전국' if province == '전국' else KB_NAMES[province]
    exact = parent + '|' + district if district else parent
    if exact in values:
        return exact
    return parent if parent in values else None


def series_metric(values, dates, region, unit='', field=None):
    key = kb_scope(region, values)
    selected = values.get(key, [])
    if field:
        selected = selected.get(field, []) if isinstance(selected, dict) else []
    value, period = latest(selected, dates)
    return metric(value, unit, period, key, '상위 지역 자료' if key and '|' in region and '|' not in key else '')


def load_feed(kind):
    candidates = []
    for folder in (ROOT / 'data', ROOT / 'cache/published/housing'):
        path = folder / (kind + '.json.gz')
        if not path.exists():
            continue
        try:
            with gzip.open(path, 'rt', encoding='utf-8') as source:
                data = json.load(source)
            if data.get('schema_version') == 1 and not data.get('failed'):
                candidates.append(data)
        except (OSError, ValueError):
            print(f'{kind}: 읽을 수 없는 집계 자료를 건너뜁니다')
    return max(candidates, key=lambda d: d['collected']) if candidates else None


def supply_metrics(region, pipeline=None, moveins=None, today=None):
    province = region.split('|')[0]
    metrics = {}
    pipeline_scope = province
    if pipeline and province in ('광주', '전남') and any(pipeline['values'].get(province, {}).get(k, [None])[-1] is None for k in ('permit','start','completion')):
        pipeline_scope = '전남광주'
    for key in ('permit','start','completion'):
        values = pipeline['values'].get(pipeline_scope, {}).get(key, []) if pipeline else []
        # 최신 공급월의 값이 없을 때 과거 개별 권역 값을 현재처럼 보여주지 않는다.
        value = values[-1] if values else None
        period = pipeline['months'][-1] if pipeline else None
        note = '아파트 월계 실적 · 시도 자료' if '|' in region else '아파트 월계 실적'
        if pipeline_scope == '전남광주':note += ' · 광주·전남 통합 공표값'
        metrics[key] = metric(value, '호', period, pipeline_scope if pipeline else None, note)
    moveins_scope = region
    if moveins and '|' in region and not moveins['values'].get(region, {}).get('district_available', False):
        moveins_scope = province
    stats = moveins['values'].get(moveins_scope) if moveins else None
    current = (today or kst_today()).strftime('%Y-%m')
    note = '예정월 기재 물량 · 30세대 이상 공동주택 · 월 미정 별도'
    if moveins_scope != region:note += ' · 시군구 주소 미확인으로 상위 지역 자료'
    for size in (6,12):
        months = [shift(current, i) for i in range(size)]
        mapping = dict(zip(moveins['months'], stats['scheduled'])) if stats else {}
        numbers = [mapping.get(m) for m in months]
        value = sum(numbers) if all(finite(v) for v in numbers) else None
        metrics[f'moveins{size}'] = metric(value, '호', months[0] + '~' + months[-1], moveins_scope if stats else None, note + ('' if value is not None else ' · 전망 범위 또는 자료 부족'))
    unknown = sum(stats['unscheduled'].values()) if stats else None
    metrics['moveins_unknown'] = metric(unknown, '호', ', '.join(sorted(stats['unscheduled'])) or '전망 기간' if stats else None, moveins_scope if stats else None,
                                       '예정 연도만 공개된 물량 · 6·12개월 합계에 넣지 않음')
    return metrics, pipeline_scope, moveins_scope


def summarize(weekly, monthly, trades, supply=None, rents=None, pipeline=None, moveins=None, today=None):
    scope = districts()
    regions = ['전국'] + PROVINCES + [g for p in PROVINCES for g in scope[p]]
    result = {}
    full = [i for i, m in enumerate(trades['months']) if m < trades['partial_from']]
    end = full[-1] if len(full) >= 3 else None
    for region in regions:
        province = region.split('|')[0]
        metrics = {}
        for kind, name in [('sale', 'price'), ('jeonse', 'jeonse')]:
            key = kb_scope(region, weekly.get(kind, {}))
            values = weekly.get(kind, {}).get(key, [])
            value, period = weekly_change(values, weekly['dates'])
            metrics[name] = metric(value, '%', period, key, '상위 지역 자료' if key and '|' in region and '|' not in key else '')
        for name, source, field in [('jeonse_ratio', 'jeonse_ratio', None), ('hai', 'hai', 'apt')]:
            series = monthly.get(source, {})
            metrics[name] = series_metric(series.get('values', {}), series.get('dates', []), region, '%' if name == 'jeonse_ratio' else '', field)
        apt = trades.get('agg', {}).get('apt', {}).get(region, {})
        rolling = apt.get('period3', {})
        samples = rolling.get('price_n', [])[end] if end is not None and rolling else None
        price = rolling.get('price', [])[end] if samples is not None and samples >= 10 else None
        period = trades['months'][end-2] + '~' + trades['months'][end] if end is not None else None
        metrics['trade_price'] = metric(price, '만원', period, region, f'가격 표본 {samples}건' if samples is not None else '수집 누락 또는 자료 없음')
        key = region.replace('|', '>')
        if len(scope.get(province, [])) == 1:
            key = province
        recovery = trades.get('recovery', {}).get(key, {})
        metrics['recovery'] = metric(recovery.get('ratio'), '%', recovery.get('from', '') + '~' + recovery.get('to', '') if recovery else None,
                                     region, f'과거 {recovery.get("years", 0)}개 동기간 평균 대비')
        if supply:
            stats = supply['values'].get(region, {})
            count, month = latest(stats.get('completed', []), supply['months'])
            metrics['completed'] = metric(count, '호', month, region, '준공 후 미분양')
            total, total_month = latest(stats.get('total', []), supply['months'])
            share = count / total * 100 if finite(count) and finite(total) and total > 0 and month == total_month else None
            metrics['supply_share'] = metric(share, '%', month, region, '전체 미분양 중 준공 후 비중')
        else:
            metrics['completed'] = metric(note='공식 공급 자료 없음')
            metrics['supply_share'] = metric(note='공식 공급 자료 없음')
        if rents:
            series = rents['values'].get(region, {})
            date = dt.date.fromisoformat(rents['collected'][:10])
            partial_from = (date.replace(day=1) - dt.timedelta(days=1)).strftime('%Y-%m')
            eligible = [i for i, m in enumerate(rents['months']) if m < partial_from and i < len(series.get('n', [])) and series['n'][i] is not None]
            i = eligible[-1] if eligible else None
            period = rents['months'][i] if i is not None else None
            deposit = series.get('deposit', [])[i] if i is not None else None
            rent = series.get('rent', [])[i] if i is not None else None
            n = series.get('jeonse_n', [])[i] if i is not None else None
            mn = series.get('monthly_n', [])[i] if i is not None else None
            metrics['rent_deposit'] = metric(deposit, '만원', period, region, f'순수 전세 {n}건 · 신고 지연을 고려해 최근 2개월 제외')
            metrics['monthly_rent'] = metric(rent, '만원/월', period, region, f'월세 {mn}건 · 보증금 차이를 보정하지 않은 금액')
        else:
            metrics['rent_deposit'] = metric(note='전월세 수집 자료 없음')
            metrics['monthly_rent'] = metric(note='전월세 수집 자료 없음')
        rates = trades.get('extra', {}).get('rates', {})
        value, period = latest(rates.get('values', {}).get('주택담보대출', []), rates.get('months', []))
        metrics['rate'] = metric(value, '%', period, '전국', '예금은행 신규취급액 주택담보대출')
        extra_metrics, _, _ = supply_metrics(region, pipeline, moveins, today)
        metrics.update(extra_metrics)
        result[region] = metrics
    data = {'schema_version': 1, 'regions': regions, 'provinces': PROVINCES, 'districts': scope,
            'metrics': result, 'sources': [
                {'name': 'KB 주간', 'kind': 'weekly', 'period': weekly.get('asof'), 'collected': None},
                {'name': 'KB 월간', 'kind': 'kb_monthly', 'period': monthly.get('asof'), 'collected': None}
            ] + [{**s, 'name': 'R-ONE 미분양' if s['name'] == '미분양' else s['name']} for s in trades.get('sources', []) if s['name'] != 'KB 월간'] + [
                {'name': name, 'kind': 'forecast' if name == '공동주택 입주예정' else 'monthly',
                 'asof': feed.get('asof') if feed else None,
                 'horizon_start': feed['months'][0] if feed else None,
                 'horizon_end': feed['months'][-1] if feed else None,
                 'period': (feed['months'][0] + '~' + feed['months'][-1] + ' · 기준 ' + feed['asof'] if feed.get('asof') else feed['months'][-1]) if feed else None,
                 'collected': feed.get('collected') if feed else None}
                for name, feed in [('국토부 공식 미분양', supply), ('국토부 전월세', rents), ('아파트 공급 실적', pipeline), ('공동주택 입주예정', moveins)]],
            'kb_names': KB_NAMES,
            'supply': {'months': supply['months'], 'values': supply['values']} if supply else None,
            'rents': {'months': rents['months'], 'values': rents['values']} if rents else None,
            'pipeline': {k:v for k,v in pipeline.items() if k != 'revision_history'} if pipeline else None, 'moveins': {k:v for k,v in moveins.items() if k != 'revision_history'} if moveins else None, 'view_month': (today or kst_today()).strftime('%Y-%m')}
    data['health'] = report(data['sources'], today)
    data['sources'] = data['health'].pop('sources')
    return data


def build():
    def read(kind):
        with (ROOT / 'dashboard/overview-input' / (kind + '.json')).open(encoding='utf-8') as f:
            return json.load(f)
    trades, supply, rents = read('trades'), load_feed('supply'), load_feed('rents')
    pipeline, moveins = load_feed('pipeline'), load_feed('moveins')
    data = summarize(read('weekly'), read('monthly'), trades, supply, rents, pipeline, moveins)
    revisions = {'schema_version': 1, 'sources': {}}
    data['revision_sources'] = []
    for kind, label, feed in [('trades', '국토부 매매', trades), ('supply', '공식 미분양', supply), ('rents', '아파트 전월세', rents), ('pipeline', '아파트 공급 실적', pipeline), ('moveins', '공동주택 입주예정', moveins)]:
        info = feed.get('revision_history', {}) if feed else {}
        revisions['sources'][kind] = info
        data['revision_sources'].append({'kind': kind, 'name': label, 'tracking_since': info.get('tracking_since'),
                                         'last_collected': feed.get('collected') if feed else None,
                                         'last_checked': info.get('last_checked'), 'events': len(info.get('events', [])),
                                         'dropped_events': info.get('dropped_events', 0), 'dropped_changes': info.get('dropped_changes', 0)})
    payload = json.dumps(revisions, ensure_ascii=False, separators=(',', ':')).encode()
    filename = 'revisions.' + hashlib.sha256(payload).hexdigest()[:12] + '.json'
    folder = ROOT / 'dashboard/overview-data'
    folder.mkdir(parents=True, exist_ok=True)
    part = folder / (filename + '.part')
    part.write_bytes(payload)
    part.replace(folder / filename)
    data['revision_file'] = 'overview-data/' + filename
    template = (ROOT / 'scripts/overview_template.html').read_text(encoding='utf-8')
    comparison = (ROOT / 'scripts/overview_comparison.js').read_text(encoding='utf-8')
    html = template.replace('/*COMPARISON*/', comparison).replace('/*DATA*/', json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/'))
    html = html.replace('/*BUILD_SHA*/', os.environ.get('GITHUB_SHA', 'local'))
    out = ROOT / 'dashboard/overview.html'
    out.write_text(html, encoding='utf-8')
    print(f'종합 화면 생성: {out} ({len(html.encode()) / 1e6:.1f}MB)')
    return out


if __name__ == '__main__':
    build()
