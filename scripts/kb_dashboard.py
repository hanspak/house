"""KB 주간시계열 엑셀로 '아파트 국면판' HTML을 만든다.

사용법:
  python3 scripts/kb_dashboard.py                      # kbdata/ 안의 가장 최근 *_주간시계열.xlsx 사용
  python3 scripts/kb_dashboard.py --drive              # 구글 드라이브 폴더의 최신 파일을 받아서 사용
  python3 scripts/kb_dashboard.py kbdata/20260921_주간시계열.xlsx

결과: dashboard/kb_dashboard_YYYYMMDD.html (기준일), dashboard/latest.html
"""
import glob
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
from kb_extract import main as extract  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def build(xlsx):
    with tempfile.TemporaryDirectory() as tmp:
        js = os.path.join(tmp, "kb.json")
        extract(xlsx, js)
        with open(js, encoding="utf-8") as f:
            data = json.load(f)
    data.pop("sentiment", None)  # 이 화면에서는 쓰지 않음
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
    print(f"생성: {out}")
    return out


if __name__ == "__main__":
    if "--drive" in sys.argv[1:]:
        from kb_drive import fetch_latest
        src = fetch_latest()
    elif len(sys.argv) > 1:
        src = sys.argv[1]
    else:
        files = sorted(glob.glob(os.path.join(ROOT, "kbdata", "*_주간시계열.xlsx")))
        if not files:
            sys.exit("kbdata/ 폴더에 *_주간시계열.xlsx 파일이 없습니다.")
        src = files[-1]
    build(src)
