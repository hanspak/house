"""한국부동산원 R-ONE(아파트 매매 거래량, 미분양)과 한국은행 ECOS(금리)를 받아 cache/extra.json으로 저장한다.

사용법: python3 scripts/market_extra.py

키: 환경변수 RONE_KEY, ECOS_KEY 또는 secrets/api_keys.json 의 rone, ecos
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# R-ONE (월) 행정구역별 아파트매매거래현황 — 전국·시도·서울 구
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


def get_json(url):
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            return json.loads(urllib.request.urlopen(req, timeout=40).read())
        except Exception:
            if attempt == 3:
                raise
            time.sleep(3 * (attempt + 1))


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


def rone_apt_trades(key, start="200601"):
    end = dt.date.today().strftime("%Y%m")
    latest = rone_rows(key, STATBL_ID=RONE_APT_TRADES, DTACYCLE_CD="MM", WRTTIME_IDTFR_ID=_last_month())
    if not latest:
        latest = rone_rows(key, STATBL_ID=RONE_APT_TRADES, DTACYCLE_CD="MM", WRTTIME_IDTFR_ID=_last_month(2))
    regions = {}
    for r in latest:
        full = r["CLS_FULLNM"]
        if r["ITM_ID"] == RONE_COUNT_ITEM and (">" not in full or full.startswith("서울>")):
            regions[r["CLS_ID"]] = full
    series = {}
    for cid, name in regions.items():
        rows = rone_rows(key, STATBL_ID=RONE_APT_TRADES, DTACYCLE_CD="MM", CLS_ID=cid, START_WRTTIME=start, END_WRTTIME=end)
        s = {r["WRTTIME_IDTFR_ID"]: r["DTA_VAL"] for r in rows if r["ITM_ID"] == RONE_COUNT_ITEM}
        series[name] = s
    months = sorted({m for s in series.values() for m in s})
    return {"months": [f"{m[:4]}-{m[4:]}" for m in months],
            "values": {n: [s.get(m) for m in months] for n, s in series.items()},
            "source": "한국부동산원 R-ONE (월) 행정구역별 아파트매매거래현황"}


def _last_month(back=1):
    d = dt.date.today().replace(day=1)
    for _ in range(back):
        d = (d - dt.timedelta(days=1)).replace(day=1)
    return d.strftime("%Y%m")


PROV17 = ["서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기",
          "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"]


def rone_unsold(key, start="200012"):
    end = dt.date.today().strftime("%Y%m")
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
    for p, a in vals.items():
        first = next((i for i, v in enumerate(a) if v is not None), len(a))
        for i in range(first):
            a[i] = 0

    def total(names):
        # 한 시·도라도 그 달 값이 없으면 합계를 만들지 않는다 (과소 집계 방지)
        return [sum(vals[p][i] for p in names) if all(vals[p][i] is not None for p in names) else None
                for i in range(len(months))]
    agg = {"전국": total(PROV17), "수도권": total([p for p in PROV17 if p in CAPITAL]),
           "지방": total([p for p in PROV17 if p not in CAPITAL])}
    return {"months": [f"{m[:4]}-{m[4:]}" for m in months], "values": {**agg, **vals},
            "source": "한국부동산원 R-ONE 미분양주택현황 (시·도 '계'를 더한 값, 단위 호. 17개 시·도가 모두 발표된 달만 전국 합계)"}


def ecos_rates(key, start="201001"):
    end = dt.date.today().strftime("%Y%m")
    series = {}
    for stat, item, name in ECOS_SERIES:
        u = f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/1000/{stat}/M/{start}/{end}/{item}"
        d = get_json(u)
        rows = d.get("StatisticSearch", {}).get("row", [])
        series[name] = {r["TIME"]: float(r["DATA_VALUE"]) for r in rows}
    months = sorted({m for s in series.values() for m in s})
    return {"months": [f"{m[:4]}-{m[4:]}" for m in months],
            "values": {n: [s.get(m) for m in months] for n, s in series.items()},
            "source": "한국은행 ECOS 722Y001(기준금리), 121Y006(예금은행 대출금리, 신규취급액 기준)"}


def main():
    rone, ecos = keys()
    out = {"collected": dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M KST")}
    if rone:
        out["apt_trades"] = rone_apt_trades(rone)
        print(f"R-ONE 아파트 매매 거래량: {len(out['apt_trades']['values'])}개 지역, "
              f"{out['apt_trades']['months'][0]} ~ {out['apt_trades']['months'][-1]}")
        out["unsold"] = rone_unsold(rone)
        u = out["unsold"]
        last = max(i for i, v in enumerate(u["values"]["전국"]) if v is not None)
        print(f"R-ONE 미분양: {u['months'][0]} ~ {u['months'][-1]}, 전국 합계는 {u['months'][last]}까지 ({u['values']['전국'][last]:,}호)")
    else:
        print("R-ONE 키가 없어 거래량은 건너뜀")
    if ecos:
        out["rates"] = ecos_rates(ecos)
        print(f"ECOS 금리: {list(out['rates']['values'])}, {out['rates']['months'][0]} ~ {out['rates']['months'][-1]}")
    else:
        print("ECOS 키가 없어 금리는 건너뜀")
    os.makedirs(os.path.join(ROOT, "cache"), exist_ok=True)
    with open(os.path.join(ROOT, "cache", "extra.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    sys.exit(main())
