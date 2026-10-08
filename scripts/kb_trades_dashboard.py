"""국토부 실거래가 + R-ONE 거래량 + ECOS 금리 (+ KB 월간 시세)로 '실거래·거래량·금리' HTML을 만든다.

사용법:
  python3 scripts/kb_trades_dashboard.py            # 실거래·R-ONE·ECOS를 새로 받고 화면 생성
  python3 scripts/kb_trades_dashboard.py --no-fetch # cache/에 있는 자료로만 화면 생성
  python3 scripts/kb_trades_dashboard.py --drive    # KB 월간 파일을 드라이브에서 받음(호가 비교용)
  python3 scripts/kb_trades_dashboard.py --snapshot # 마지막 완전한 전국 집계로 즉시 화면 생성

결과: dashboard/trades.html
"""
import datetime as dt
import argparse
import gzip
import hashlib
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
from kb_status import update_status  # noqa: E402
from trade_regions import PROVINCES, KB_NAMES, districts, normalize_trades, normalize_rone
from trade_analysis import (aggregate_profiles, trade_recovery, source_dates,
                            ANALYSIS_VERSION, MIN_PRICE_SAMPLE, AREA_OPTIONS, AGE_OPTIONS)
from overview_data import save as save_overview

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOW_PRICES = [10000, 15000, 20000]  # 만원: 1억, 1.5억, 2억 (목록에 담는 최대치는 2억)
TYPE_NAMES = {"apt": "아파트", "rh": "연립·다세대", "offi": "오피스텔"}


def aggregate(tr):
    """전국·시도·시군구 월별 및 실제 거래를 합친 3개월 통계."""
    return aggregate_profiles(tr, districts(), filtered=False)['all-all']


def low_price_list(tr, months_n=12):
    """연립·다세대와 오피스텔 중 2억 이하 거래(최근 12개월). 화면에서 1억/1.5억/2억으로 거른다."""
    keep = set(tr["months"][-months_n:])
    out = []
    for kind in ("rh", "offi"):
        for gu, rows in tr["trades"][kind].items():
            for r in rows:
                if r[0][:7] in keep and r[5] <= max(LOW_PRICES):
                    out.append([kind, gu] + r[:8])  # kind, gu, date, dong, name, area, floor, amount, build_year, house_type
    out.sort(key=lambda x: x[2], reverse=True)
    return out


def kb_monthly_series(path):
    """KB 월간 전국·시·도 아파트·연립 중위 매매가(만원)."""
    from kb_monthly_extract import main as mextract
    with tempfile.TemporaryDirectory() as tmp:
        js = os.path.join(tmp, "km.json")
        mextract(path, js)
        m = json.load(open(js, encoding="utf-8"))
    s = m["median_sale"]
    return {"asof": m["asof"], "dates": s["dates"],
            "values": {p: s['values'][name] for p, name in {'전국': '전국', **KB_NAMES}.items()
                       if name in s['values']}}


PLACEHOLDER = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>실거래·거래량·금리</title></head><body style="font-family:-apple-system,'Apple SD Gothic Neo',sans-serif;max-width:640px;margin:40px auto;padding:0 20px;line-height:1.6">
<p><a href="index.html">주간 아파트 국면판</a> · <a href="monthly.html">월간 주택 시장판</a></p>
<h1>실거래·거래량·금리</h1><p>API 키가 등록되지 않아 이 화면을 만들지 못했습니다. 저장소 Settings → Secrets에
<code>DATA_GO_KR_KEY</code>, <code>RONE_KEY</code>, <code>ECOS_KEY</code>를 등록하면 다음 실행부터 나타납니다.</p></body></html>"""


def write_placeholder():
    out = os.path.join(ROOT, "dashboard", "trades.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(PLACEHOLDER)
    print(f"실거래 키가 없어 안내 페이지만 생성: {out}")


def build(fetch=True, drive=False):
    if fetch:
        from molit_trades import collect
        from market_extra import main as extra_main
        try:
            collect(24)
        except SystemExit as e:  # 키 없음
            print(e)
            if not os.path.exists(os.path.join(ROOT, "cache", "trades.json")):
                return write_placeholder()
        extra_main()
    if not os.path.exists(os.path.join(ROOT, "cache", "trades.json")):
        return write_placeholder()
    tr = normalize_trades(json.load(open(os.path.join(ROOT, "cache", "trades.json"), encoding="utf-8")))
    extra_path = os.path.join(ROOT, "cache", "extra.json")
    extra = json.load(open(extra_path, encoding="utf-8")) if os.path.exists(extra_path) else {}
    if 'apt_trades' in extra:
        extra['apt_trades'] = normalize_rone(extra['apt_trades'])

    kb = None
    if drive:
        from kb_drive import fetch_latest
        mp = fetch_latest("monthly", required=False)
    else:
        from kb_monthly_dashboard import latest_local
        mp = latest_local("월간 주택 시계열")
    if mp:
        kb = kb_monthly_series(mp)

    # 신고 기한(계약 후 30일) 때문에 이번 달·지난달 건수는 아직 늘어나는 중
    today = dt.date.fromisoformat(tr["collected"][:10])
    profiles = aggregate_profiles(tr, districts())
    data = {
        "months": tr["months"], "collected": tr["collected"], "failed": tr.get("failed", 0),
        "provinces": PROVINCES, "districts": districts(),
        "agg": profiles.pop("all-all"), "profiles": profiles, "low": low_price_list(tr),
        "extra": extra, "kb": kb,
        "partial_from": (today.replace(day=1) - dt.timedelta(days=1)).strftime("%Y-%m"),
        "type_names": TYPE_NAMES,
    }
    data['analysis_version'] = ANALYSIS_VERSION
    data['filters'] = {'area': AREA_OPTIONS, 'age': AGE_OPTIONS, 'year': today.year}
    data['min_price_sample'] = MIN_PRICE_SAMPLE
    data['recovery'] = trade_recovery(extra.get('apt_trades'), data['partial_from'])
    data['sources'] = source_dates(data)
    if not data['failed']:
        save_snapshot(data, os.path.join(ROOT, 'cache', 'published', 'trades.json.gz'))
    return render(data)


def save_snapshot(data, path):
    """게시용 집계 자료만 저장한다. API 키와 원본 응답은 포함하지 않는다."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    with open(path + '.part', 'wb') as f:
        f.write(gzip.compress(payload, mtime=0))
    os.replace(path + '.part', path)


def build_snapshot(path=None):
    """수집을 기다리지 않고 마지막 완전한 전국 자료로 현재 템플릿을 렌더링한다."""
    paths = [path] if path else [os.path.join(ROOT, 'data', 'trades.json.gz'),
                                os.path.join(ROOT, 'cache', 'published', 'trades.json.gz')]
    candidates = []
    for candidate in paths:
        if not os.path.exists(candidate):
            continue
        with gzip.open(candidate, 'rt', encoding='utf-8') as f:
            data = json.load(f)
        if data.get('failed') or data.get('provinces') != PROVINCES or data.get('analysis_version') != ANALYSIS_VERSION:
            continue
        if any(v is None for kind in data['agg'].values() for series in kind.values() for v in series['n']):
            continue
        candidates.append(data)
    if not candidates:
        raise SystemExit('게시 가능한 전국 집계 자료가 없습니다.')
    return render(max(candidates, key=lambda d: d['collected']))


def render(data):
    save_overview('trades', {k: data[k] for k in ('months', 'collected', 'partial_from', 'agg', 'extra', 'recovery', 'sources') if k in data}, ROOT)
    data = dict(data)
    profiles = data.pop('profiles', {})
    out_dir = os.path.join(ROOT, 'dashboard')
    asset_dir = os.path.join(out_dir, 'trades-data')
    os.makedirs(asset_dir, exist_ok=True)
    data['profile_files'] = {}
    for profile, stats in profiles.items():
        payload = json.dumps(stats, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        name = profile + '.' + hashlib.sha256(payload).hexdigest()[:12] + '.json'
        with open(os.path.join(asset_dir, name + '.part'), 'wb') as f:
            f.write(payload)
        os.replace(os.path.join(asset_dir, name + '.part'), os.path.join(asset_dir, name))
        data['profile_files'][profile] = 'trades-data/' + name
    with open(os.path.join(ROOT, "scripts", "trades_template.html"), encoding="utf-8") as f:
        tpl = f.read()
    html = tpl.replace("/*DATA*/", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    out_dir = os.path.join(ROOT, "dashboard")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "trades.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write('<!doctype html><html lang="ko"><head><meta charset="utf-8">'
                f'<meta name="build-commit" content="{os.environ.get("GITHUB_SHA", "local")}">'
                '<meta name="viewport" content="width=device-width,initial-scale=1"></head><body>' + html + "</body></html>")
    update_status(trades=data["collected"][:10])
    print(f"생성: {out} ({os.path.getsize(out) / 1e6:.1f}MB, 1억~2억 이하 목록 {len(data['low'])}건)")
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--no-fetch', action='store_true')
    parser.add_argument('--drive', action='store_true')
    parser.add_argument('--snapshot', action='store_true', help='마지막 완전한 집계 자료로 빠르게 화면 생성')
    args = parser.parse_args()
    if args.snapshot:
        build_snapshot()
    else:
        build(fetch=not args.no_fetch, drive=args.drive)
