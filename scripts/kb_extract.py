"""KB 주간시계열 엑셀에서 시각화용 데이터를 JSON으로 추출한다.

사용법: python3 scripts/kb_extract.py kbdata/20260921_주간시계열.xlsx out.json

시트의 열 순서(시·도 다음에 그 하위 지역이 이어짐)를 그대로 읽어 시·도별 하위 지역 목록을 만든다.
같은 이름(중구·서구 등)이 여러 시·도에 있으므로 하위 지역 id는 "시도|지역" 형식이다.
"""
import json
import sys
import warnings

import pandas as pd

warnings.filterwarnings("ignore")

# (시트상 이름, 화면 이름, 하위 지역 단위). 단위가 "시"이면 이름이 '시'로 끝나는 열만 하위 지역으로 쓴다
# (시 아래의 구는 건너뜀). None이면 하위 지역 없음.
PROVINCES = [
    ("서울특별시", "서울특별시", "구"),
    ("부산광역시", "부산광역시", "구·군"),
    ("대구광역시", "대구광역시", "구·군"),
    ("인천광역시", "인천광역시", "구"),
    ("(구)광주광역시", "광주광역시", "구"),
    ("대전광역시", "대전광역시", "구"),
    ("울산광역시", "울산광역시", "구·군"),
    ("세종특별자치시", "세종특별자치시", None),
    ("경기도", "경기도", "시"),
    ("강원특별자치도", "강원특별자치도", "시"),
    ("충청북도", "충청북도", "시"),
    ("충청남도", "충청남도", "시"),
    ("전북특별자치도", "전북특별자치도", "시"),
    ("(구)전라남도", "전라남도", "시"),
    ("경상북도", "경상북도", "시"),
    ("경상남도", "경상남도", "시"),
    ("제주특별자치도", "제주특별자치도", None),
]
# 시·도 블록을 끝내는 집계 열
STOPS = {"6개광역시", "5개광역시", "수도권", "기타지방", "전남광주통합특별시", "제주도"}
SEOUL_GROUP_MARKERS = {"강북14개구": "강북 14개 구", "강남11개구": "강남 11개 구"}
CAPITAL = {"서울특별시", "인천광역시", "경기도"}
SENTIMENT = {
    "5.매수우위": ("매수우위지수", "buyer"),
    "6.매매거래활발": ("매매거래활발지수", "trade"),
    "7.전세수급": ("전세수급지수", "jeonse_supply"),
    "8.전세거래활발": ("전세거래활발지수", "jeonse_trade"),
}


def read_sheet(path, sheet):
    """(열 이름 목록, 날짜 인덱스, 열번호→시리즈) 반환."""
    d = pd.read_excel(path, sheet_name=sheet, header=None)
    names = [str(x).strip() for x in d.iloc[1]]
    dates = pd.to_datetime(d.iloc[3:, 0], errors="coerce")
    body = d.iloc[3:][dates.notna().values]
    idx = pd.DatetimeIndex(dates[dates.notna()])
    cols = {c: pd.Series(pd.to_numeric(body.iloc[:, c], errors="coerce").values, index=idx) for c in range(1, d.shape[1])}
    return names, idx, cols


def hierarchy(names, cols, last_date):
    """시·도 → 하위 지역 열번호 목록. 마지막 주에 값이 없는 열(폐지된 구 등)은 제외 목록으로."""
    sheet_to_prov = {p[0]: p for p in PROVINCES}
    prov_names = set(sheet_to_prov) | STOPS
    pos = {n: i for i, n in enumerate(names) if n in sheet_to_prov}
    out, dropped = [], []
    for sheet_name, label, unit in PROVINCES:
        c0 = pos[sheet_name]
        children, groups, group = [], {}, None
        if unit:
            for c in range(c0 + 1, len(names)):
                n = names[c]
                if n in prov_names:
                    break
                if n in SEOUL_GROUP_MARKERS:
                    group = SEOUL_GROUP_MARKERS[n]
                    continue
                if unit == "시" and not n.endswith("시"):
                    continue
                s = cols[c].dropna()
                if s.empty or s.index[-1] < last_date:
                    dropped.append(f"{label} {n}")
                    continue
                children.append((c, n))
                if group:
                    groups[f"{label}|{n}"] = group
        out.append({"col": c0, "label": label, "unit": unit, "children": children, "groups": groups})
    return out, dropped


def ser(s, idx):
    s = s.reindex(idx)
    return [None if pd.isna(v) else round(float(v), 3) for v in s]


def read_sentiment(path, sheet, label):
    d = pd.read_excel(path, sheet_name=sheet, header=None)
    region = d.iloc[1].ffill()
    dates = pd.to_datetime(d.iloc[4:, 0], errors="coerce")
    out = {}
    for c in range(1, d.shape[1]):
        if str(d.iloc[2, c]).strip() != label:
            continue
        name = str(region[c]).split()[0]
        if name not in out:
            s = pd.to_numeric(d.iloc[4:, c], errors="coerce")
            s.index = dates
            out[name] = s
    df = pd.DataFrame(out)
    df = df[df.index.notna()].dropna(how="all")
    return {"dates": [x.strftime("%Y-%m-%d") for x in df.index],
            "values": {k: [None if pd.isna(v) else round(float(v), 2) for v in df[k]] for k in df.columns}}


def main(path, out):
    names, idx, sale_cols = read_sheet(path, "3.매매지수")
    jnames, jidx, jeonse_cols = read_sheet(path, "4.전세지수")
    if names != jnames:
        raise SystemExit("매매지수와 전세지수 시트의 지역 열 순서가 다릅니다.")
    last = idx[-1]
    provs, dropped = hierarchy(names, sale_cols, last)

    sale, jeonse, views = {}, {}, []

    def add(key, c):
        sale[key] = ser(sale_cols[c], idx)
        jeonse[key] = ser(jeonse_cols[c], idx)

    add("전국", names.index("전국"))
    for p in provs:
        add(p["label"], p["col"])
        kids = []
        for c, n in p["children"]:
            key = f"{p['label']}|{n}"
            add(key, c)
            kids.append(key)
        if kids:
            gnames = list(dict.fromkeys(p["groups"].values()))
            views.append({"id": p["label"], "name": p["label"], "unit": p["unit"], "children": kids,
                          "groups": p["groups"], "groupNames": gnames})
    nation_kids = [p["label"] for p in provs]
    views.insert(0, {"id": "전국", "name": "전국 시·도 비교", "unit": "시·도", "children": nation_kids,
                     "groups": {k: ("수도권" if k in CAPITAL else "지방") for k in nation_kids},
                     "groupNames": ["수도권", "지방"]})

    data = {
        "source": path.split("/")[-1],
        "asof": last.strftime("%Y-%m-%d"),
        "base": "2026-01-12=100",
        "dates": [d.strftime("%Y-%m-%d") for d in idx],
        "views": views,
        "sale": sale,
        "jeonse": jeonse,
        "dropped": dropped,
        "sentiment": {key: read_sentiment(path, sh, label) for sh, (label, key) in SENTIMENT.items()},
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{out}: 기준 {data['asof']}, {len(idx)}주, 화면 {len(views)}개, 지역 {len(sale)}개, 제외 {dropped}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
