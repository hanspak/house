"""국토교통부 실거래가(매매) API로 서울 25개 구의 아파트·연립다세대·오피스텔 거래를 모은다.

사용법:
  python3 scripts/molit_trades.py                 # 최근 24개월 수집 후 cache/trades.json 생성
  python3 scripts/molit_trades.py --months 36

키: 환경변수 DATA_GO_KR_KEY 또는 secrets/api_keys.json 의 data_go_kr (공공데이터포털 '일반 인증키(Decoding)')

- 월·구·유형별 응답을 cache/molit/<유형>/<구코드>_<YYYYMM>.json 에 저장한다.
  신고 기한(계약 후 30일)과 해제 신고를 반영하려고 최근 3개월은 매번 다시 받고, 그 이전 달은 캐시를 쓴다.
- 해제된 거래(cdealType = 'O')는 제외한다.
- 금액 단위는 만원, 면적은 전용 ㎡.
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "cache", "molit")
SEOUL = {
    "11110": "종로구", "11140": "중구", "11170": "용산구", "11200": "성동구", "11215": "광진구",
    "11230": "동대문구", "11260": "중랑구", "11290": "성북구", "11305": "강북구", "11320": "도봉구",
    "11350": "노원구", "11380": "은평구", "11410": "서대문구", "11440": "마포구", "11470": "양천구",
    "11500": "강서구", "11530": "구로구", "11545": "금천구", "11560": "영등포구", "11590": "동작구",
    "11620": "관악구", "11650": "서초구", "11680": "강남구", "11710": "송파구", "11740": "강동구",
}
TYPES = {
    "apt": ("RTMSDataSvcAptTradeDev", "getRTMSDataSvcAptTradeDev", "aptNm"),
    "rh": ("RTMSDataSvcRHTrade", "getRTMSDataSvcRHTrade", "mhouseNm"),
    "offi": ("RTMSDataSvcOffiTrade", "getRTMSDataSvcOffiTrade", "offiNm"),
}
REFRESH_MONTHS = 3


def api_key():
    k = os.environ.get("DATA_GO_KR_KEY")
    if not k:
        p = os.path.join(ROOT, "secrets", "api_keys.json")
        if os.path.exists(p):
            k = json.load(open(p, encoding="utf-8")).get("data_go_kr")
    if not k:
        sys.exit("공공데이터포털 키가 없습니다. DATA_GO_KR_KEY 환경변수나 secrets/api_keys.json의 data_go_kr을 설정하세요.")
    return k


def months_back(n, today=None):
    today = today or dt.date.today()
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        out.append(f"{y:04d}{m:02d}")
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return out[::-1]


def fetch(key, kind, lawd, ym):
    svc, op, name_tag = TYPES[kind]
    items, page = [], 1
    while True:
        q = urllib.parse.urlencode({"serviceKey": key, "LAWD_CD": lawd, "DEAL_YMD": ym, "pageNo": page, "numOfRows": 1000})
        url = f"https://apis.data.go.kr/1613000/{svc}/{op}?{q}"
        for attempt in range(6):
            try:
                body = urllib.request.urlopen(url, timeout=40).read().decode("utf-8")
                root = ET.fromstring(body)
                break
            except Exception as e:
                if attempt == 5:
                    raise
                # 429(요청 과다)는 길게 쉬었다가 다시 시도
                time.sleep((10 if "429" in str(e) else 2) * (attempt + 1))
        code = root.findtext(".//resultCode")
        if code not in ("000", "00"):
            raise RuntimeError(f"{kind} {lawd} {ym}: {code} {root.findtext('.//resultMsg')}")
        for it in root.iter("item"):
            f = {c.tag: (c.text or "").strip() for c in it}
            if f.get("cdealType") == "O":
                continue  # 해제된 거래
            try:
                amount = int(f["dealAmount"].replace(",", ""))
                area = float(f["excluUseAr"])
            except (KeyError, ValueError):
                continue
            items.append([
                f"{int(f['dealYear']):04d}-{int(f['dealMonth']):02d}-{int(f['dealDay']):02d}",
                f.get("umdNm", ""), f.get(name_tag, ""), round(area, 2),
                int(f["floor"]) if f.get("floor", "").lstrip("-").isdigit() else None,
                amount, int(f["buildYear"]) if f.get("buildYear", "").isdigit() else None,
                f.get("houseType", ""), f.get("jibun", ""),
            ])
        total = int(root.findtext(".//totalCount") or 0)
        if page * 1000 >= total:
            return items
        page += 1


def collect(months=24):
    key = api_key()
    yms = months_back(months)
    refresh = set(yms[-REFRESH_MONTHS:])
    jobs = [(k, l, ym) for k in TYPES for l in SEOUL for ym in yms]
    stats = {"api": 0, "cache": 0}

    def one(job):
        kind, lawd, ym = job
        path = os.path.join(CACHE, kind, f"{lawd}_{ym}.json")
        if ym not in refresh and os.path.exists(path):
            stats["cache"] += 1
            return job, json.load(open(path, encoding="utf-8"))
        rows = fetch(key, kind, lawd, ym)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False)
        stats["api"] += 1
        return job, rows

    out = {k: {SEOUL[l]: [] for l in SEOUL} for k in TYPES}
    failed = []

    def safe(job):
        try:
            return one(job)
        except Exception as e:  # 한 달치가 실패해도 나머지는 계속 (다음 실행 때 다시 받음)
            failed.append(f"{job[0]} {SEOUL[job[1]]} {job[2]}: {str(e)[:80]}")
            return job, None

    with ThreadPoolExecutor(max_workers=2) as ex:
        for (kind, lawd, ym), rows in ex.map(safe, jobs):
            if rows:
                out[kind][SEOUL[lawd]].extend(rows)
    if failed:
        print(f"경고: {len(failed)}건 수집 실패 (다음 실행 때 다시 시도)\n  " + "\n  ".join(failed[:5]))
    for kind in out:
        for gu in out[kind]:
            out[kind][gu].sort(key=lambda r: r[0])
    data = {
        "fields": ["date", "dong", "name", "area", "floor", "amount", "build_year", "house_type", "jibun"],
        "months": [f"{y[:4]}-{y[4:]}" for y in yms],
        "collected": dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M KST"),
        "trades": out,
        "failed": len(failed),
    }
    path = os.path.join(ROOT, "cache", "trades.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    n = {k: sum(len(v) for v in out[k].values()) for k in out}
    print(f"실거래 수집: API {stats['api']}회, 캐시 {stats['cache']}건, 거래 {n} → {path}")
    return data


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--months", type=int, default=24)
    collect(ap.parse_args().months)
