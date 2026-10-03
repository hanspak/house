"""KB 월간 주택(·오피스텔) 시계열로 '월간 주택 시장판' HTML을 만든다.

사용법:
  python3 scripts/kb_monthly_dashboard.py            # kbdata/ 안의 가장 최근 월간 주택·오피스텔 파일 사용
  python3 scripts/kb_monthly_dashboard.py --drive    # 구글 드라이브에서 최신 파일을 받아서 사용

결과: dashboard/monthly_YYYYMM.html (기준월), dashboard/monthly.html, dashboard/status.json(기준월 기록)
오피스텔 파일이 없으면 오피스텔 화면만 '자료 없음'으로 나온다.
"""
import glob
import json
import os
import shutil
import sys
import tempfile
import unicodedata

sys.path.insert(0, os.path.dirname(__file__))
from kb_monthly_extract import main as extract  # noqa: E402
from kb_status import update_status  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def latest_local(pattern):
    files = sorted(f for f in glob.glob(os.path.join(ROOT, "kbdata", "*.xlsx"))
                   if pattern in unicodedata.normalize("NFC", os.path.basename(f)))
    return files[-1] if files else None


def build(housing, officetel=None):
    with tempfile.TemporaryDirectory() as tmp:
        js = os.path.join(tmp, "km.json")
        extract(housing, js, officetel)
        with open(js, encoding="utf-8") as f:
            data = json.load(f)
    # 시 아래 구 단위는 아파트 지수만 쓰므로 나머지 유형은 시·도 이상만 남겨 파일 크기를 줄인다.
    for key, v in data["index"].items():
        if not key.endswith("_apt"):
            v["values"] = {r: a for r, a in v["values"].items() if "|" not in r}
    tpl = open(os.path.join(ROOT, "scripts", "monthly_template.html"), encoding="utf-8").read()
    html = tpl.replace("/*DATA*/", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    out_dir = os.path.join(ROOT, "dashboard")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"monthly_{data['asof'].replace('-', '')}.html")
    page = ('<!doctype html><html lang="ko"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"></head><body>'
            + html + "</body></html>")
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    shutil.copyfile(out, os.path.join(out_dir, "monthly.html"))
    update_status(monthly=data["asof"], officetel=data.get("officetel", {}).get("asof"))
    print(f"생성: {out}")
    return out


if __name__ == "__main__":
    if "--drive" in sys.argv[1:]:
        from kb_drive import fetch_latest
        housing = fetch_latest("monthly")
        officetel = fetch_latest("officetel", required=False)
    else:
        housing, officetel = latest_local("월간 주택 시계열"), latest_local("월간 오피스텔 시계열")
        if not housing:
            sys.exit("kbdata/ 폴더에 'YYYYMM_월간 주택 시계열.xlsx' 파일이 없습니다.")
    build(housing, officetel)
