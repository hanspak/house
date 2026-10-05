"""국토부 법정동코드와 KB/R-ONE의 17개 시·도 통계 권역 연결."""
import json
from pathlib import Path

PROVINCES = ['서울', '부산', '대구', '인천', '광주', '대전', '울산', '세종',
             '경기', '강원', '충북', '충남', '전북', '전남', '경북', '경남', '제주']
KB_NAMES = dict(zip(PROVINCES, [
    '서울특별시', '부산광역시', '대구광역시', '인천광역시', '광주광역시',
    '대전광역시', '울산광역시', '세종특별자치시', '경기도', '강원특별자치도',
    '충청북도', '충청남도', '전북특별자치도', '전라남도', '경상북도', '경상남도',
    '제주특별자치도']))
REGIONS = json.loads(Path(__file__).with_name('trade_regions.json').read_text())['regions']


def region_id(code):
    r = REGIONS[code]
    return f"{r['province']}|{r['district']}"


def districts():
    return {p: sorted({region_id(c) for c, r in REGIONS.items() if r['province'] == p})
            for p in PROVINCES}


def normalize_trades(data):
    """기존 서울 구별 캐시도 전국 스키마로 읽는다. 미수집 지역은 추가하지 않는다."""
    if not data.get('districts'):
        data['trades'] = {k: {f'서울|{g}': rows for g, rows in v.items()}
                          for k, v in data['trades'].items()}
        data['districts'] = {'서울': list(data['trades']['apt'])}
    return data


def normalize_rone(data):
    """통합특별시의 기존 권역 및 시군구를 17개 시·도 선택에 연결한다."""
    values = dict(data['values'])
    for name, series in list(values.items()):
        parts = name.split('>')
        if parts[0] == '전남광주' and len(parts) > 1:
            if parts[1] in ('(구)광주', '(구)전남'):
                target = parts[1].replace('(구)', '')
            else:
                province = '광주' if parts[1] in ('동구', '서구', '남구', '북구', '광산구') else '전남'
                target = '>'.join([province] + parts[1:])
        else:
            target = name.replace('(구)', '')
        values[target] = series
    scope = districts()
    for province in ('광주', '전남'):
        child_keys = [g.replace('|', '>') for g in scope[province]]
        previous = values.get(province, [None] * len(data['months']))
        values[province] = [v if v is not None else
                            sum(values[k][i] for k in child_keys)
                            if all(k in values and values[k][i] is not None for k in child_keys)
                            else None for i, v in enumerate(previous)]
    data['values'] = values
    return data
