"""실거래 원자료로 만드는 보조 신호: 거래 주체·방식, 반복거래 가격지수, 직전 1년 최고가 경신 비율.

모두 전체 면적·연식 기준이며 전국·시도·시군구 단위로 월별 값을 낸다.
- 거래 주체·방식: 직거래, 법인 매수, 법인 매도 건수. 이전 형식 캐시(해당 칸 없음)가 섞인 지역·월은
  비율을 계산할 수 없으므로 known(형식 확인 건수)을 함께 둔다. known < n 이면 화면에서 '보강 중'으로 표시한다.
- 반복거래 지수: 같은 단지(법정동·지번·이름)·같은 전용면적이 다시 거래된 가격 변화로 월별 지수를 추정한다
  (Bailey-Muth-Nourse 방식, 첫 달 = 100). 거래된 집의 구성이 바뀌어도 흔들리지 않는다.
- 최고가 경신 비율: 같은 단지·면적의 직전 12개월 거래가 있는 거래 중, 그 최고가보다 비싸게 거래된 비율.
"""
import math
from trade_analysis import shift_month

MAX_LOG_RATIO = math.log(2)  # 두 거래 가격이 2배 넘게 차이 나면 다른 집·입력 오류일 가능성이 커 뺀다.
MIN_PAIRS = 20               # 그 달이 들어간 반복거래 쌍이 이보다 적으면 지수를 비운다(표시 기준).
LOOKBACK = 12                # 최고가 비교 기간(개월)
DEALING, BUYER, SELLER = 9, 10, 11


def unit_key(row):
    """같은 집으로 보는 기준: 법정동·지번·이름·전용면적. 층·동은 구분하지 않는다."""
    return (row[1], row[8], row[2], round(row[3], 1))


def regions_of(scope):
    """시군구 → [시군구, 시도, 전국]"""
    return {d: (d, p, '전국') for p, ids in scope.items() for d in ids}


def empty(regions, months, keys):
    return {g: {k: [0] * months for k in keys} for g in regions}


def participants(rows_by_district, months, scope, missing):
    index = {m: i for i, m in enumerate(months)}
    up = regions_of(scope)
    out = empty(list(scope) + list(up) + ['전국'], len(months), ('n', 'known', 'direct', 'buyer_corp', 'seller_corp'))
    for district, rows in rows_by_district.items():
        if district not in up:
            continue
        for row in rows:
            i = index.get(row[0][:7])
            if i is None:
                continue
            known = len(row) > SELLER
            for g in up[district]:
                c = out[g]
                c['n'][i] += 1
                if known:
                    c['known'][i] += 1
                    c['direct'][i] += row[DEALING] == '직거래'
                    c['buyer_corp'][i] += row[BUYER] == '법인'
                    c['seller_corp'][i] += row[SELLER] == '법인'
    blank(out, months, scope, missing)
    return out


def blank(out, months, scope, missing):
    """수집 누락 월은 0건이 아니라 자료 없음(None). 상위 지역은 하위 한 곳이라도 누락이면 비운다."""
    index = {m: i for i, m in enumerate(months)}
    members = {g: [g] for ids in scope.values() for g in ids}
    members.update(scope)
    members['전국'] = [g for ids in scope.values() for g in ids]
    for g, ids in members.items():
        absent = {index[m] for d in ids for m in missing.get(d, []) if m in index}
        for series in out[g].values():
            for i in absent:
                series[i] = None


def solve(a, b):
    """작은 대칭 연립방정식(가우스 소거). 특이하면 None."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[p][c]) < 1e-12:
            return None
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c and m[r][c]:
                f = m[r][c] / m[c][c]
                m[r] = [x - f * y for x, y in zip(m[r], m[c])]
    return [m[i][n] / m[i][i] for i in range(n)]


def repeat_index(pairs, months_n):
    """pairs = [(s, t, log 가격비)]. 첫 달 기준 지수(100)와 달별 쌍 수. 쌍이 부족한 달은 지수를 비운다."""
    count = [0] * months_n
    for s, t, _ in pairs:
        count[s] += 1
        count[t] += 1
    valid = [i for i in range(months_n) if count[i] >= MIN_PAIRS]
    if not valid:
        return {'index': [None] * months_n, 'pairs': count}
    base = valid[0]
    params = [i for i in valid if i != base]
    pos = {i: j for j, i in enumerate(params)}
    k = len(params)
    a = [[0.0] * k for _ in range(k)]
    b = [0.0] * k
    for s, t, r in pairs:
        if (s != base and s not in pos) or (t != base and t not in pos):
            continue
        terms = [(pos[t], 1.0)] if t != base else []
        terms += [(pos[s], -1.0)] if s != base else []
        for x, wx in terms:
            b[x] += wx * r
            for y, wy in terms:
                a[x][y] += wx * wy
    beta = solve(a, b) if k else []
    if beta is None:
        return {'index': [None] * months_n, 'pairs': count}
    index = [None] * months_n
    index[base] = 100.0
    for i, j in pos.items():
        index[i] = round(100 * math.exp(beta[j]), 2)
    return {'index': index, 'pairs': count}


def price_signals(rows_by_district, months, scope, missing):
    """반복거래 지수와 최고가 경신 비율."""
    index = {m: i for i, m in enumerate(months)}
    up = regions_of(scope)
    pairs = {g: [] for g in list(scope) + list(up) + ['전국']}
    highs = empty(pairs, len(months), ('eligible', 'new_high'))
    for district, rows in rows_by_district.items():
        if district not in up:
            continue
        units = {}
        for row in rows:
            i = index.get(row[0][:7])
            if i is not None and row[5] > 0 and row[3] and row[3] > 0:
                units.setdefault(unit_key(row), []).append((row[0], i, row[5]))
        for trades in units.values():
            trades.sort()
            for j, (_, t, price) in enumerate(trades):
                if j:
                    _, s, before = trades[j - 1]
                    r = math.log(price / before)
                    if s < t and abs(r) <= MAX_LOG_RATIO:
                        for g in up[district]:
                            pairs[g].append((s, t, r))
                if t >= LOOKBACK:
                    prior = [p for _, m, p in trades[:j] if t - LOOKBACK <= m < t]
                    if prior:
                        for g in up[district]:
                            highs[g]['eligible'][t] += 1
                            highs[g]['new_high'][t] += price > max(prior)
    for g in highs:
        for key in ('eligible', 'new_high'):
            highs[g][key][:LOOKBACK] = [None] * min(LOOKBACK, len(months))
    blank(highs, months, scope, missing)
    out = {}
    for g, p in pairs.items():
        out[g] = {**repeat_index(p, len(months)), **highs[g]}
    return out


def build(tr, scope):
    """{유형: {지역: {participants..., index, pairs, eligible, new_high}}}"""
    months = tr['months']
    result = {}
    for kind, districts in tr['trades'].items():
        missing = tr.get('missing', {}).get(kind, {})
        part = participants(districts, months, scope, missing)
        price = price_signals(districts, months, scope, missing)
        result[kind] = {g: {**part[g], **price[g]} for g in part}
    return {'months': months, 'min_pairs': MIN_PAIRS, 'lookback': LOOKBACK, 'kinds': result}
