"""국토교통부 실거래가(매매) API로 전국 시·군·구의 아파트·연립다세대·오피스텔 거래를 모은다.

사용법:
  python3 scripts/molit_trades.py                 # 최근 24개월 수집 후 cache/trades.json 생성
  python3 scripts/molit_trades.py --months 36

키: 환경변수 DATA_GO_KR_KEY 또는 secrets/api_keys.json 의 data_go_kr (공공데이터포털 '일반 인증키(Decoding)')

- 월·시군구·유형별 응답을 cache/molit/<유형>/<시군구코드>_<YYYYMM>.json 에 저장한다.
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
import threading
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from trade_regions import REGIONS, districts, region_id
from data_archive import save_rows, save_cached_rows

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "cache", "molit")
TYPES = {
    "apt": ("RTMSDataSvcAptTradeDev", "getRTMSDataSvcAptTradeDev", "aptNm"),
    "rh": ("RTMSDataSvcRHTrade", "getRTMSDataSvcRHTrade", "mhouseNm"),
    "offi": ("RTMSDataSvcOffiTrade", "getRTMSDataSvcOffiTrade", "offiNm"),
}
REFRESH_MONTHS = 3
REQUEST_INTERVAL = 0.25  # 서비스별 초당 최대 4회. 여러 스레드의 순간 요청 집중을 피한다.
REQUEST_LOCK = threading.Lock()
NEXT_REQUEST = {}


def pace(kind):
    with REQUEST_LOCK:
        now = time.monotonic()
        delay = max(0, NEXT_REQUEST.get(kind, now) - now)
        NEXT_REQUEST[kind] = now + delay + REQUEST_INTERVAL
    if delay:
        time.sleep(delay)


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
        attempts = int(os.environ.get('MOLIT_API_ATTEMPTS', '6'))
        if not 1 <= attempts <= 6:
            raise ValueError('MOLIT_API_ATTEMPTS는 1~6이어야 합니다')
        for attempt in range(attempts):
            try:
                pace(kind)
                body = urllib.request.urlopen(url, timeout=40).read().decode("utf-8")
                root = ET.fromstring(body)
                break
            except Exception as e:
                if attempt == attempts - 1:
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


def collect(months=24, workers=4, cached_only=False):
    if months < 1 or workers < 1:
        raise ValueError("months와 workers는 1 이상이어야 합니다")
    key = None if cached_only else api_key()
    yms = months_back(months)
    refresh = set(yms[-REFRESH_MONTHS:])
    jobs = [(k, l, ym) for l in REGIONS for ym in yms for k in TYPES]
    stats = {"api": 0, "cache": 0}
    cached_times = []

    def one(job):
        kind, lawd, ym = job
        path = os.path.join(CACHE, kind, f"{lawd}_{ym}.json")
        if (cached_only or ym not in refresh) and os.path.exists(path):
            stats["cache"] += 1
            cached_times.append(os.path.getmtime(path))
            with open(path, encoding="utf-8") as f:
                rows = json.load(f)
            save_cached_rows(ROOT, 'trades', kind, lawd, ym, rows, path)
            return job, rows
        if cached_only:
            raise FileNotFoundError(path)
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                previous = json.load(f)
            save_cached_rows(ROOT, 'trades', kind, lawd, ym, previous, path)
        rows = fetch(key, kind, lawd, ym)
        save_rows(ROOT, 'trades', kind, lawd, ym, rows)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + '.part', "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False)
        os.replace(path + '.part', path)
        stats["api"] += 1
        return job, rows

    out = {k: {region_id(l): [] for l in REGIONS} for k in TYPES}
    failed = []
    missing = {k: {} for k in TYPES}
    counts = {k: {} for k in TYPES}

    def safe(job):
        try:
            return one(job)
        except Exception as e:  # 한 달치가 실패해도 나머지는 계속 (다음 실행 때 다시 받음)
            failed.append(f"{job[0]} {region_id(job[1])} {job[2]}: {type(e).__name__}")
            return job, None

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, ((kind, lawd, ym), rows) in enumerate(ex.map(safe, jobs), 1):
            rid = region_id(lawd)
            if rows is None:
                missing[kind].setdefault(rid, []).append(f"{ym[:4]}-{ym[4:]}")
            else:
                # 개편 전·후 코드가 같은 과거 자료를 돌려줄 때만 중복을 제거한다.
                # 한 코드 안의 동일한 거래 여러 건은 유지한다 (행만으로 거래 ID를 알 수 없음).
                seen = counts[kind].setdefault(rid, Counter())
                batch = Counter(tuple(r) for r in rows)
                for row, n in batch.items():
                    out[kind][rid].extend([list(row) for _ in range(max(0, n - seen[row]))])
                    seen[row] = max(seen[row], n)
            if i % 500 == 0:
                print(f"실거래 수집 진행: {i}/{len(jobs)} (실패 {len(failed)}건)", flush=True)
    if failed:
        print(f"경고: {len(failed)}건 수집 실패 (다음 실행 때 다시 시도)\n  " + "\n  ".join(failed[:5]))
    for kind in out:
        for gu in out[kind]:
            out[kind][gu].sort(key=lambda r: r[0])
    collected = (dt.datetime.fromtimestamp(max(cached_times), dt.timezone(dt.timedelta(hours=9)))
                 if cached_only and cached_times else dt.datetime.now(dt.timezone(dt.timedelta(hours=9))))
    data = {
        "fields": ["date", "dong", "name", "area", "floor", "amount", "build_year", "house_type", "jibun"],
        "months": [f"{y[:4]}-{y[4:]}" for y in yms],
        "collected": collected.strftime("%Y-%m-%d %H:%M KST"),
        "trades": out,
        "districts": districts(),
        "missing": missing,
        "failed": len(failed),
    }
    path = os.path.join(ROOT, "cache", "trades.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    n = {k: sum(len(v) for v in out[k].values()) for k in out}
    print(f"실거래 수집: API {stats['api']}회, 캐시 {stats['cache']}건, 거래 {n} → {path}")
    return data


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--months", type=int, default=24)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--cached-only", action='store_true', help='월별 캐시만 모으고 미수집 월을 표시')
    args = ap.parse_args()
    collect(args.months, args.workers, args.cached_only)
