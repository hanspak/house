"""KB 주간시계열 엑셀로 '아파트 국면판'(국면·흐름·심리·역사 비교) HTML을 만든다.

사용법:
  python3 scripts/kb_dashboard.py                      # kbdata/ 안의 가장 최근 *_주간시계열.xlsx 사용
  python3 scripts/kb_dashboard.py --drive              # 구글 드라이브 폴더의 최신 파일을 받아서 사용
  python3 scripts/kb_dashboard.py kbdata/20260921_주간시계열.xlsx

결과: dashboard/kb_dashboard_YYYYMMDD.html (기준일), dashboard/latest.html

월간 주택 시계열 파일이 있으면(로컬 kbdata/ 또는 --drive) 선택 지역 상세에 월간 지표 요약을 함께 넣는다.
"""
import glob
import json
import os
import shutil
import sys
import tempfile
import unicodedata

sys.path.insert(0, os.path.dirname(__file__))
from kb_extract import main as extract  # noqa: E402
from kb_status import update_status  # noqa: E402
from overview_data import save as save_overview

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def latest_local(pattern):
    files = sorted(f for f in glob.glob(os.path.join(ROOT, "kbdata", "*.xlsx"))
                   if pattern in unicodedata.normalize("NFC", os.path.basename(f)))
    return files[-1] if files else None


def monthly_summary(path):
    """월간 주택 시계열에서 주간 화면에 붙일 요약: 전세가율·월간 전년비(하위 지역까지), 중위가격·전망(시·도)."""
    from kb_monthly_extract import main as mextract

    def last2(a, back=12):
        idx = [i for i, v in enumerate(a or []) if v is not None]
        if not idx:
            return None
        i = idx[-1]
        return [a[i], a[i - back] if i - back >= 0 else None]

    with tempfile.TemporaryDirectory() as tmp:
        js = os.path.join(tmp, "km.json")
        mextract(path, js)
        m = json.load(open(js, encoding="utf-8"))
    apt = m["index"]["sale_apt"]["values"]
    out = {"asof": m["asof"], "jr": {}, "yoy": {}, "med": {}, "outlook": {}}
    for k, a in m["jeonse_ratio"]["values"].items():
        v = last2(a)
        if v:
            out["jr"][k] = [round(x, 2) if x is not None else None for x in v]
    for k, a in apt.items():
        v = last2(a)
        if v and v[1]:
            out["yoy"][k] = round((v[0] / v[1] - 1) * 100, 2)
    for k in m["median_sale"]["values"]:
        s_, j_ = m["median_sale"]["values"][k].get("apt"), m["median_jeonse"]["values"].get(k, {}).get("apt")
        out["med"][k] = {"sale": (last2(s_) or [None])[0], "jeonse": (last2(j_) or [None])[0]}
    for k in m["outlook_sale"]["values"]:
        out["outlook"][k] = {"sale": (last2(m["outlook_sale"]["values"][k]) or [None])[0],
                             "jeonse": (last2(m["outlook_jeonse"]["values"].get(k)) or [None])[0]}
    out["regions"] = ["전국", "수도권"] + [k for k in m["index"]["sale_all"]["values"] if "|" not in k]
    return out


def build(xlsx, monthly_xlsx=None):
    with tempfile.TemporaryDirectory() as tmp:
        js = os.path.join(tmp, "kb.json")
        extract(xlsx, js)
        with open(js, encoding="utf-8") as f:
            data = json.load(f)
    if monthly_xlsx:
        data["monthly"] = monthly_summary(monthly_xlsx)
    save_overview('weekly', data, ROOT)
    tpl = open(os.path.join(ROOT, "scripts", "dashboard_template.html"), encoding="utf-8").read()
    html = tpl.replace("/*DATA*/", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    out_dir = os.path.join(ROOT, "dashboard")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"kb_dashboard_{data['asof'].replace('-', '')}.html")
    # 브라우저에서 바로 열 수 있도록 문서 골격을 붙인다.
    page = ('<!doctype html><html lang="ko"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"></head><body>'
            + html + "</body></html>")
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    shutil.copyfile(out, os.path.join(out_dir, "latest.html"))
    update_status(weekly=data["asof"])
    print(f"생성: {out}")
    return out


if __name__ == "__main__":
    monthly = None
    if "--drive" in sys.argv[1:]:
        from kb_drive import fetch_latest
        src = fetch_latest()
        monthly = fetch_latest("monthly", required=False)
    elif len(sys.argv) > 1:
        src = sys.argv[1]
    else:
        files = sorted(glob.glob(os.path.join(ROOT, "kbdata", "*_주간시계열.xlsx")))
        if not files:
            sys.exit("kbdata/ 폴더에 *_주간시계열.xlsx 파일이 없습니다.")
        src = files[-1]
    build(src, monthly or latest_local("월간 주택 시계열"))
