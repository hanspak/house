"""실거래 분석 규칙. 화면과 독립적으로 집계·조건 필터·기간 비교를 계산한다."""
import statistics

ANALYSIS_VERSION = 2
MIN_PRICE_SAMPLE = 10  # 표시 정책이며 통계적 신뢰구간 기준이 아니다.
AREA_OPTIONS = {'all': '전체 면적', 'small': '60㎡ 이하', 'medium': '60㎡ 초과~85㎡ 이하', 'large': '85㎡ 초과'}
AGE_OPTIONS = {'all': '전체 연식', 'new': '5년 이하', 'middle': '6~20년', 'old': '21년 이상'}


def median(values):
    return round(statistics.median(values), 1) if values else None


def quantile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    pos = (len(values) - 1) * fraction
    lo = int(pos)
    hi = min(lo + 1, len(values) - 1)
    return round(values[lo] + (values[hi] - values[lo]) * (pos - lo), 1)


def conditions(row, year):
    area = row[3]
    area_key = ('small' if area <= 60 else 'medium' if area <= 85 else 'large') if area and area > 0 else None
    built = row[6]
    age = year - built if isinstance(built, (int, float)) and 1800 <= built <= year else None
    age_key = None if age is None else 'new' if age <= 5 else 'middle' if age <= 20 else 'old'
    return area_key, age_key


def summarize(month_rows, missing):
    n, price_n, ppa_n, price, ppa, q1, q3 = [], [], [], [], [], [], []
    rolling = {key: [] for key in ('n', 'price_n', 'ppa_n', 'price', 'ppa', 'q1', 'q3')}
    for i, rows in enumerate(month_rows):
        valid = [r for r in rows if r[5] > 0]
        values = [r[5] for r in valid]
        pp = [r[5] / r[3] for r in valid if r[3] > 0]
        absent = i in missing
        n.append(None if absent else len(rows))
        price_n.append(None if absent else len(values))
        ppa_n.append(None if absent else len(pp))
        price.append(None if absent else median(values))
        ppa.append(None if absent else median(pp))
        q1.append(None if absent else quantile(values, .25))
        q3.append(None if absent else quantile(values, .75))
        indices = range(i - 2, i + 1)
        complete = i >= 2 and not any(j in missing for j in indices)
        pooled = [r for j in indices for r in month_rows[j] if r[5] > 0] if complete else []
        vals = [r[5] for r in pooled]
        metrics = {'n': sum(n[j] for j in indices) if complete else None,
                   'price_n': len(vals) if complete else None,
                   'ppa_n': sum(r[3] > 0 for r in pooled) if complete else None,
                   'price': median(vals), 'ppa': median([r[5] / r[3] for r in pooled if r[3] > 0]),
                   'q1': quantile(vals, .25), 'q3': quantile(vals, .75)}
        for key, value in metrics.items():
            rolling[key].append(value)
    return {'n': n, 'price_n': price_n, 'ppa_n': ppa_n, 'price': price, 'ppa': ppa, 'q1': q1, 'q3': q3, 'period3': rolling}


def aggregate_profiles(tr, scope, filtered=True):
    """조건별 지역·월 통계. 수집 누락은 필터를 적용해도 그대로 유지한다."""
    months = tr['months']
    month_index = {m: i for i, m in enumerate(months)}
    year = int(tr.get('collected', months[-1])[:4])
    profiles = {f'{area}-{age}': {} for area in AREA_OPTIONS for age in AGE_OPTIONS} if filtered else {'all-all': {}}
    members = {g: [g] for ids in scope.values() for g in ids}
    members.update(scope)
    members['전국'] = [g for ids in scope.values() for g in ids]
    for kind, districts in tr['trades'].items():
        buckets = {profile: {g: [[] for _ in months] for g in members} for profile in profiles}
        for province, ids in scope.items():
            for district in ids:
                for row in districts.get(district, []):
                    index = month_index.get(row[0][:7])
                    if index is None:
                        continue
                    area, age = conditions(row, year)
                    for a in ['all'] + ([area] if area else []):
                        for y in ['all'] + ([age] if age else []):
                            if f'{a}-{y}' not in buckets:
                                continue
                            for region in (district, province, '전국'):
                                buckets[f'{a}-{y}'][region][index].append(row)
        for profile in profiles:
            result = {}
            for region, ids in members.items():
                absent = {month_index[m] for g in ids for m in tr.get('missing', {}).get(kind, {}).get(g, []) if m in month_index}
                if any(g not in districts for g in ids):
                    absent.update(range(len(months)))
                result[region] = summarize(buckets[profile][region], absent)
            profiles[profile][kind] = result
        print(f'조건별 집계 완료: {kind}', flush=True)
    return profiles


def shift_month(month, back):
    serial = int(month[:4]) * 12 + int(month[5:]) - 1 - back
    return f'{serial // 12:04d}-{serial % 12 + 1:02d}'


def trade_recovery(series, partial_from):
    """미완료월 제외, 최근 3개월과 직전 5년 동기간 평균 비교. 최소 3개 기간."""
    result = {}
    if not series:
        return result
    months = series['months']
    for region, values in series['values'].items():
        by_month = dict(zip(months, values))
        ends = [m for m, v in by_month.items() if m < partial_from and v is not None]
        if not ends:
            continue
        end = max(ends)
        def total(back):
            data = [by_month.get(shift_month(end, back + j)) for j in range(3)]
            return sum(data) if all(v is not None for v in data) else None
        current = total(0)
        history = [total(12 * y) for y in range(1, 6)]
        history = [v for v in history if v is not None]
        baseline = statistics.mean(history) if len(history) >= 3 else None
        result[region] = {'from': shift_month(end, 2), 'to': end, 'n': current,
                          'baseline': round(baseline, 1) if baseline is not None else None,
                          'years': len(history), 'ratio': round(current / baseline * 100, 1) if current is not None and baseline else None}
    return result


def source_dates(data):
    result = [{'name': '국토부 실거래', 'period': data['months'][-1], 'collected': data['collected'], 'basis': '계약월 · 최근월 집계 중'}]
    for key, label, basis in [('apt_trades', 'R-ONE 거래량', '공식 거래통계'), ('unsold', '미분양', '월말 현황'), ('rates', 'ECOS 금리', '전국 공통')]:
        series = data.get('extra', {}).get(key)
        if series:
            available = [i for i in range(len(series['months'])) if any(i < len(v) and v[i] is not None for v in series['values'].values())]
            result.append({'name': label, 'period': series['months'][max(available)] if available else None,
                           'collected': series.get('collected', data['extra'].get('collected')), 'basis': basis})
    if data.get('kb'):
        result.append({'name': 'KB 월간', 'period': data['kb']['asof'], 'collected': None, 'basis': '조사 시세 · 수집일 기록 없음'})
    return result
