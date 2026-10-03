"""대시보드에 쓰인 자료의 기준일을 dashboard/status.json에 기록하고, 오래됐는지 점검한다.

사용법 (GitHub Actions에서 호출):
  python3 scripts/kb_status.py check     # 표준출력으로 stale=true|false, message=... 를 내보냄

판정 기준 (오늘 날짜 기준):
  주간: 기준일이 14일 넘게 지났으면 오래됨 (KB 주간 자료는 매주 나옴)
  월간 주택·오피스텔: 기준월이 2개월 넘게 지났으면 오래됨 (매월 말 공표)
  실거래: 수집일이 3일 넘게 지났으면 오래됨 (매일 수집, 키가 없으면 점검하지 않음)
"""
import datetime as dt
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "dashboard", "status.json")
WEEKLY_DAYS, MONTHLY_MONTHS, TRADES_DAYS = 14, 2, 3


def update_status(**kw):
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    st = json.load(open(PATH, encoding="utf-8")) if os.path.exists(PATH) else {}
    st.update({k: v for k, v in kw.items() if v})
    st["built"] = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M KST")
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)


def check(today=None):
    today = today or dt.date.today()
    st = json.load(open(PATH, encoding="utf-8")) if os.path.exists(PATH) else {}
    msgs = []
    if "weekly" in st:
        age = (today - dt.date.fromisoformat(st["weekly"])).days
        if age > WEEKLY_DAYS:
            msgs.append(f"주간 자료 기준일 {st['weekly']} ({age}일 전) — 드라이브에 새 주간 파일을 올려 주세요")
    else:
        msgs.append("주간 자료 기준일 기록 없음")
    for key, label in [("monthly", "월간 주택"), ("officetel", "월간 오피스텔")]:
        if key in st:
            y, m = map(int, st[key].split("-"))
            gap = (today.year - y) * 12 + today.month - m
            if gap > MONTHLY_MONTHS:
                msgs.append(f"{label} 자료 기준월 {st[key]} ({gap}개월 전) — 새 월간 파일을 올려 주세요")
        elif key == "monthly":
            msgs.append("월간 주택 자료 기준월 기록 없음")
    if "trades" in st:
        age = (today - dt.date.fromisoformat(st["trades"])).days
        if age > TRADES_DAYS:
            msgs.append(f"실거래 수집일 {st['trades']} ({age}일 전) — API 키나 공공데이터포털 상태를 확인해 주세요")
    return msgs


if __name__ == "__main__":
    if sys.argv[1:] == ["check"]:
        msgs = check()
        print(f"stale={'true' if msgs else 'false'}")
        print("message=" + (" / ".join(msgs) if msgs else "모든 자료가 최신입니다"))
