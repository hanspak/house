"""국토부 실거래가 + R-ONE 거래량 + ECOS 금리 (+ KB 월간 시세)로 '실거래·거래량·금리' HTML을 만든다.

사용법:
  python3 scripts/kb_trades_dashboard.py            # 실거래·R-ONE·ECOS를 새로 받고 화면 생성
  python3 scripts/kb_trades_dashboard.py --no-fetch # cache/에 있는 자료로만 화면 생성
  python3 scripts/kb_trades_dashboard.py --drive    # KB 월간 파일을 드라이브에서 받음(호가 비교용)

결과: dashboard/trades.html
"""
import datetime as dt
import json
import os
import statistics
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
from kb_status import update_status  # noqa: E402
from trade_regions import PROVINCES, KB_NAMES, districts, normalize_trades, normalize_rone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOW_PRICES = [10000, 15000, 20000]  # 만원: 1억, 1.5억, 2억 (목록에 담는 최대치는 2억)
TYPE_NAMES = {"apt": "아파트", "rh": "연립·다세대", "offi": "오피스텔"}


def med(xs):
    return round(statistics.median(xs), 1) if xs else None


def aggregate(tr):
    """시·군·구, 시·도, 전국 월별 통계. 누락된 지역·월은 0건과 구분한다."""
    months = tr["months"]
    agg = {}
    for kind, by_gu in tr["trades"].items():
        agg[kind] = {}
        expected = districts()
        groups = {g: [g] for ids in expected.values() for g in ids}
        groups.update(expected)
        groups['전국'] = [g for ids in expected.values() for g in ids]
        for gu, members in groups.items():
            rows = [r for g in members for r in by_gu.get(g, [])]
            missing = {m for g in members for m in tr.get('missing', {}).get(kind, {}).get(g, [])}
            if any(g not in by_gu for g in members):
                missing.update(months)
            bym = {m: [] for m in months}
            for r in rows:
                m = r[0][:7]
                if m in bym:
                    bym[m].append(r)
            agg[kind][gu] = {
                "n": [None if m in missing else len(bym[m]) for m in months],
                "price": [None if m in missing else med([r[5] for r in bym[m]]) for m in months],
                "ppa": [None if m in missing else med([r[5] / r[3] for r in bym[m] if r[3] > 0]) for m in months],
            }
    return agg


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
    today = dt.date.today()
    data = {
        "months": tr["months"], "collected": tr["collected"], "failed": tr.get("failed", 0),
        "provinces": PROVINCES, "districts": districts(),
        "agg": aggregate(tr), "low": low_price_list(tr),
        "extra": extra, "kb": kb,
        "partial_from": (today.replace(day=1) - dt.timedelta(days=1)).strftime("%Y-%m"),
        "type_names": TYPE_NAMES,
    }
    tpl = open(os.path.join(ROOT, "scripts", "trades_template.html"), encoding="utf-8").read()
    html = tpl.replace("/*DATA*/", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    out_dir = os.path.join(ROOT, "dashboard")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "trades.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write('<!doctype html><html lang="ko"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1"></head><body>' + html + "</body></html>")
    update_status(trades=tr["collected"][:10])
    print(f"생성: {out} ({os.path.getsize(out) / 1e6:.1f}MB, 1억~2억 이하 목록 {len(data['low'])}건)")


if __name__ == "__main__":
    build(fetch="--no-fetch" not in sys.argv[1:], drive="--drive" in sys.argv[1:])
