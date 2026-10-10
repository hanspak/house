"""한국부동산원 R-ONE(아파트 매매 거래량, 미분양)과 한국은행 ECOS(금리)를 받아 cache/extra.json으로 저장한다.

사용법: python3 scripts/market_extra.py

키: 환경변수 RONE_KEY, ECOS_KEY 또는 secrets/api_keys.json 의 rone, ecos
"""
import datetime as dt
import argparse
import gzip
import math
import re
from pathlib import Path
from collection_runs import write
from data_archive import record, save_file
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from trade_regions import normalize_rone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# R-ONE (월) 행정구역별 아파트매매거래현황 — 전국·시도·시군구
RONE_APT_TRADES = "A_2024_00554"
RONE_COUNT_ITEM = 100001  # 동(호)수
# R-ONE 미분양주택현황 — 시·도 '계'와 시군구. 전국 합계는 없어 시·도 '계'를 더한다.
RONE_UNSOLD = "T237973129847263"
CAPITAL = {"서울", "인천", "경기"}
# ECOS: (통계표, 항목, 이름)
ECOS_SERIES = [
    ("722Y001", "0101000", "기준금리"),
    ("121Y006", "BECBLA0302", "주택담보대출"),
    ("121Y006", "BECBLA030201", "고정형 주담대"),
    ("121Y006", "BECBLA030202", "변동형 주담대"),
    ("121Y006", "BECBLA03041", "전세자금대출"),
]


def keys():
    k = {}
    p = os.path.join(ROOT, "secrets", "api_keys.json")
    if os.path.exists(p):
        k = json.load(open(p, encoding="utf-8"))
    return os.environ.get("RONE_KEY") or k.get("rone"), os.environ.get("ECOS_KEY") or k.get("ecos")


def get_json(url, timeout=40, waits=(3, 6, 9)):
    """waits의 간격으로 재시도한다(시도 횟수 = len(waits) + 1)."""
    for attempt in range(len(waits) + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
        except Exception:
            if attempt == len(waits):
                raise
            time.sleep(waits[attempt])


# ECOS는 GitHub Actions에서 몇 분씩 연결이 안 되는 일이 있어(URLError), 짧게 기다리며 더 오래 재시도한다.
# 최악 5×25초 + 110초 = 235초로 수집 제한 5분 안에 끝난다.
ECOS_TIMEOUT, ECOS_WAITS = 25, (5, 15, 30, 60)


def rone_rows(key, **q):
    out, page = [], 1
    while True:
        u = "https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do?" + urllib.parse.urlencode(
            {"KEY": key, "Type": "json", "pIndex": page, "pSize": 1000, **q})
        d = get_json(u)
        body = d.get("SttsApiTblData")
        if not isinstance(body, list):
            return out  # INFO-200: 데이터 없음
        rows = body[1]["row"] if len(body) > 1 else []
        out += rows
        if len(rows) < 1000:
            return out
        page += 1


# 이전 자료가 있으면 최근 이 개월 수만 다시 받아 덮어쓴다(R-ONE의 과거 값 정정 반영).
# 전체 기간을 매번 받으면 요청이 수십~수백 번이라 GitHub Actions(해외)에서 5분 제한을 넘긴다.
RONE_REFRESH_MONTHS = 24


def refresh_start(previous, default):
    """이전 자료의 마지막 달에서 RONE_REFRESH_MONTHS개월 전(YYYYMM). 이전 자료가 없으면 default(전체 기간)."""
    if not valid_feed(previous):
        return default
    y, m = map(int, previous['months'][-1].split('-'))
    m -= RONE_REFRESH_MONTHS - 1
    while m < 1:
        y, m = y - 1, m + 12
    return max(default, f"{y:04d}{m:02d}")


def merge_feed(previous, fresh):
    """새로 받은 달은 새 값으로, 그 이전 달은 이전 자료로 채운다."""
    if not valid_feed(previous):
        return fresh
    months = sorted(set(previous['months']) | set(fresh['months']))
    old = {n: dict(zip(previous['months'], a)) for n, a in previous['values'].items()}
    new = {n: dict(zip(fresh['months'], a)) for n, a in fresh['values'].items()}
    window = set(fresh['months'])
    values = {n: [(new.get(n, {}) if m in window else old.get(n, {})).get(m) for m in months]
              for n in list(old) + [n for n in new if n not in old]}
    return {**fresh, 'months': months, 'values': values}


def rone_apt_trades(key, start="200601", previous=None):
    end = dt.date.today().strftime("%Y%m")
    start = refresh_start(previous, start)
    # 지역별로 따로 요청하지 않고(약 290회) 전 지역을 기간으로 한 번에 받는다.
    rows = rone_rows(key, STATBL_ID=RONE_APT_TRADES, DTACYCLE_CD="MM", START_WRTTIME=start, END_WRTTIME=end)
    counts = [r for r in rows if r["ITM_ID"] == RONE_COUNT_ITEM]
    # 지역 이름은 가장 최근 달의 이름을 쓴다. 과거 행은 이름이 비어 있을 수 있고, 최근 달에 없는 폐지 지역은 뺀다.
    latest = max((r["WRTTIME_IDTFR_ID"] for r in counts), default=None)
    regions = {r["CLS_ID"]: r["CLS_FULLNM"] for r in counts if r["WRTTIME_IDTFR_ID"] == latest and r["CLS_FULLNM"]}
    series = {name: {} for name in regions.values()}
    for r in counts:
        if r["CLS_ID"] in regions:
            series[regions[r["CLS_ID"]]][r["WRTTIME_IDTFR_ID"]] = r["DTA_VAL"]
    months = sorted({m for s in series.values() for m in s})
    fresh = normalize_rone({"months": [f"{m[:4]}-{m[4:]}" for m in months],
            "values": {n: [s.get(m) for m in months] for n, s in series.items()},
            "source": "한국부동산원 R-ONE (월) 행정구역별 아파트매매거래현황"})
    return merge_feed(previous, fresh)


def _last_month(back=1):
    d = dt.date.today().replace(day=1)
    for _ in range(back):
        d = (d - dt.timedelta(days=1)).replace(day=1)
    return d.strftime("%Y%m")


PROV17 = ["서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기",
          "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"]


def rone_unsold(key, start="200012", previous=None):
    end = dt.date.today().strftime("%Y%m")
    whole_range = not valid_feed(previous)
    start = refresh_start(previous, start)
    rows = rone_rows(key, STATBL_ID=RONE_UNSOLD, DTACYCLE_CD="MM", START_WRTTIME=start, END_WRTTIME=end)
    prov = {p: {} for p in PROV17}
    for r in rows:
        full = r.get("CLS_FULLNM") or ""
        name = full[:-2] if full.endswith(">계") else None
        if name in prov:  # 원자료의 '전국>계' 등 집계 행은 쓰지 않고 시·도를 직접 더한다
            prov[name][r["WRTTIME_IDTFR_ID"]] = r["DTA_VAL"]
    months = sorted({m for s in prov.values() for m in s})
    vals = {p: [s.get(m) for m in months] for p, s in prov.items()}
    # 세종(2012년 출범)처럼 자료가 시작되기 전 달은 0으로 본다. 그 뒤의 빈 달은 그대로 비워 둔다.
    # 최근 기간만 받을 때는 앞쪽 빈 달이 '출범 전'이 아니므로 채우지 않는다.
    for p, a in vals.items():
        first = next((i for i, v in enumerate(a) if v is not None), len(a)) if whole_range else 0
        for i in range(first):
            a[i] = 0

    def total(names):
        # 한 시·도라도 그 달 값이 없으면 합계를 만들지 않는다 (과소 집계 방지)
        return [sum(vals[p][i] for p in names) if all(vals[p][i] is not None for p in names) else None
                for i in range(len(months))]
    agg = {"전국": total(PROV17), "수도권": total([p for p in PROV17 if p in CAPITAL]),
           "지방": total([p for p in PROV17 if p not in CAPITAL])}
    return merge_feed(previous, {"months": [f"{m[:4]}-{m[4:]}" for m in months], "values": {**agg, **vals},
            "source": "한국부동산원 R-ONE 미분양주택현황 (시·도 '계'를 더한 값, 단위 호. 17개 시·도가 모두 발표된 달만 전국 합계)"})


def ecos_rates(key, start="201001", previous=None):
    # ECOS는 통계당 요청 1번이라 빠르므로 항상 전체 기간을 받는다.
    end = dt.date.today().strftime("%Y%m")
    series = {}
    for stat, item, name in ECOS_SERIES:
        u = f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/1000/{stat}/M/{start}/{end}/{item}"
        d = get_json(u, timeout=ECOS_TIMEOUT, waits=ECOS_WAITS)
        rows = d.get("StatisticSearch", {}).get("row", [])
        series[name] = {r["TIME"]: float(r["DATA_VALUE"]) for r in rows}
    months = sorted({m for s in series.values() for m in s})
    return {"months": [f"{m[:4]}-{m[4:]}" for m in months],
            "values": {n: [s.get(m) for m in months] for n, s in series.items()},
            "source": "한국은행 ECOS 722Y001(기준금리), 121Y006(예금은행 대출금리, 신규취급액 기준)"}


def valid_feed(data):
    if not isinstance(data, dict):
        return False
    months, values = data.get('months'), data.get('values')
    return (isinstance(months, list) and bool(months) and
            all(isinstance(m, str) and re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', m) for m in months) and
            months == sorted(set(months)) and isinstance(values, dict) and bool(values) and
            all(isinstance(a, list) and len(a) == len(months) and
                all(v is None or isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in a)
                for a in values.values()) and
            any(v is not None for a in values.values() for v in a))


def load_extra(root=ROOT):
    root = Path(root)
    out, candidates = {}, []
    for path in (root / 'data/trades.json.gz', root / 'cache/published/trades.json.gz'):
        if path.exists():
            try:
                with gzip.open(path, 'rt', encoding='utf-8') as f:
                    candidates.append(json.load(f).get('extra', {}))
            except (OSError, ValueError, AttributeError):
                print('Unreadable extra baseline skipped', flush=True)
    path = root / 'cache/extra.json'
    if path.exists():
        try:
            candidates.append(json.loads(path.read_text(encoding='utf-8')))
        except (OSError, ValueError):
            print('Unreadable extra cache skipped', flush=True)
    for key in ('apt_trades', 'unsold', 'rates'):
        feeds = [{**c[key], 'collected': c[key].get('collected', c.get('collected'))}
                 for c in candidates if isinstance(c, dict) and valid_feed(c.get(key))]
        path = root / 'cache/published/extra' / (key + '.json')
        if path.exists():
            try:
                feed = json.loads(path.read_text(encoding='utf-8'))
                if valid_feed(feed):
                    feeds.append(feed)
            except (OSError, ValueError):
                print('Unreadable extra feed skipped', flush=True)
        if feeds:
            # Prefer the dedicated feed on equal timestamps (legacy stamps have minute precision).
            out[key] = max(reversed(feeds), key=lambda f: f.get('collected') or '')
    out['collected'] = max((f.get('collected') or '' for f in out.values()), default='')
    return out


def main(source=None):
    rone, ecos = keys()
    failures = 0
    baseline = load_extra(ROOT)
    for key, fetcher, auth in [('apt_trades', rone_apt_trades, rone), ('unsold', rone_unsold, rone), ('rates', ecos_rates, ecos)]:
        if source and source != key:
            continue
        try:
            if not auth:
                raise ValueError('missing_key')
            previous = {k: v for k, v in baseline.get(key, {}).items() if k != 'collected'} or None
            data = fetcher(auth, previous=previous)
            if not valid_feed(data):
                raise ValueError('invalid_series')
            data['collected'] = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime('%Y-%m-%d %H:%M KST')
            dest = Path(ROOT) / 'cache/published/extra' / (key + '.json')
            if dest.exists():
                try:
                    previous = json.loads(dest.read_text())
                    previous_period = previous['months'][-1] if valid_feed(previous) else 'previous-period-unknown'
                except (ValueError, TypeError, KeyError):
                    previous_period = 'previous-period-unknown'
                save_file(ROOT, 'extra', key, previous_period, dest, origin='cache_import')
            record(ROOT, 'extra', key, '', data['months'][-1],
                   json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8'), 'json', origin='api')
            write(dest, data)
            print(f'{key}: {data["months"][0]} ~ {data["months"][-1]}', flush=True)
        except Exception as error:
            failures += 1
            # URLError의 reason은 소켓 오류 설명뿐이라 주소(API 키)가 들어가지 않는다. 다른 오류는 내용을 남기지 않는다.
            reason = f': {error.reason}' if isinstance(error, urllib.error.URLError) and not isinstance(error, urllib.error.HTTPError) else ''
            print(f'{key}: failed ({type(error).__name__}{reason}); previous data retained', flush=True)
    write(Path(ROOT) / 'cache/extra.json', load_extra(ROOT))
    return 1 if failures else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', choices=['apt_trades', 'unsold', 'rates'])
    sys.exit(main(parser.parse_args().source))
