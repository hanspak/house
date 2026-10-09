"""공식 공동주택 입주예정 CSV를 지역·월별로 집계한다. 월 미정은 별도로 보존한다."""
import csv
import datetime as dt
import io
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request

from data_revisions import save_published
from data_archive import save_file
from trade_regions import PROVINCES, districts

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'https://www.data.go.kr/data/15111714/fileData.do'


def shift(month, offset):
    serial = int(month[:4]) * 12 + int(month[5:]) - 1 + offset
    return f'{serial // 12:04d}-{serial % 12 + 1:02d}'


def district_key(province, address, scope):
    if province == '세종':
        return scope[province][0]
    tokens = address.split()[1:]
    # 기준 시점의 인천 중·동·서구 주소는 개편 후 경계를 구별할 수 없다.
    if province == '인천' and tokens and tokens[0] in ('중구', '동구', '서구'):
        return None
    matches = [g for g in scope[province] if tokens[:len(g.split('|')[1].split())] == g.split('|')[1].split()]
    return max(matches, key=len) if matches else None


def parse_csv(body, asof, expected_rows=None):
    try:
        text = body.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = body.decode('cp949')
    reader = csv.DictReader(io.StringIO(text))
    required = {'입주예정월', '지역', '사업유형', '주소', '아파트명', '세대수'}
    if not required.issubset(reader.fieldnames or []):
        raise ValueError('입주예정 CSV 항목이 맞지 않습니다')
    first = shift(asof[:7], 1)
    months = [shift(first, i) for i in range(24)]
    scope = districts()
    groups = ['전국'] + PROVINCES + [g for ids in scope.values() for g in ids]
    values = {g: {'scheduled': [0] * 24, 'unscheduled': {}, 'projects': 0, 'unmatched_units': 0, 'district_available': True} for g in groups}
    count, total = 0, 0
    for row in reader:
        province = row['지역'].strip()
        month = row['입주예정월'].strip()
        try:
            units = int(row['세대수'].replace(',', ''))
        except ValueError:
            raise ValueError('입주예정 세대수가 올바르지 않습니다')
        if province not in PROVINCES or units < 0:
            raise ValueError('입주예정 지역·세대수 범위가 맞지 않습니다')
        unknown = re.fullmatch(r'(\d{4})-00', month)
        if month not in months and not (unknown and any(m[:4] == unknown[1] for m in months)):
            raise ValueError('입주예정 기간이 공식 기준일의 2년 범위와 다릅니다')
        district = district_key(province, row['주소'], scope)
        members = ['전국', province] + ([district] if district else [])
        for key in members:
            series = values[key]
            series['projects'] += 1
            if unknown:
                year = unknown[1]
                series['unscheduled'][year] = series['unscheduled'].get(year, 0) + units
            else:
                series['scheduled'][months.index(month)] += units
        if not district:
            values[province]['unmatched_units'] += units
            # 알 수 없는 주소가 어느 시군구에 속하는지 추정하지 않는다.
            for key in scope[province]:
                values[key]['district_available'] = False
        count += 1;total += units
    if not count or expected_rows is not None and count != expected_rows:
        raise ValueError('입주예정 전체 행 수 점검 실패')
    national = values['전국']
    if sum(national['scheduled']) + sum(national['unscheduled'].values()) != total:
        raise ValueError('입주예정 전국 합계가 맞지 않습니다')
    for key, series in values.items():
        if not series['district_available']:
            series['scheduled'] = [None] * 24
            series['unscheduled'] = {}
    return {'schema_version': 1, 'asof': asof, 'months': months, 'values': values,
            'row_count': count, 'total_units': total, 'source': SOURCE,
            'basis': '30세대 이상 공동주택 · 예정월 미정 별도 · 실제 준공과 다름'}


def collect():
    with urllib.request.urlopen(SOURCE, timeout=30) as response:
        html = response.read().decode('utf-8')
    match = re.search(r'입주예정물량정보_(\d{8})', html)
    detail = re.search(r'id="publicDataDetailPk"[^>]+value="([^"]+)"', html)
    if not match or not detail:
        raise ValueError('입주예정 공식 기준일·다운로드 항목을 찾지 못했습니다')
    asof = dt.datetime.strptime(match[1], '%Y%m%d').date().isoformat()
    query = urllib.parse.urlencode({'publicDataDetailPk': detail[1], 'publicDataPk': '15111714',
                                   'atchFileId': '', 'fileDetailSn': '1', 'publicDataTyCode': 'PR0051'})
    # 포털의 메타데이터 contentUrl이 과거의 다른 첨부를 가리킬 수 있어 공식 버튼과 같은 조회를 사용한다.
    with urllib.request.urlopen('https://www.data.go.kr/tcs/dss/selectFileDataDownload.do?' + query, timeout=30) as response:
        info = json.load(response)
    if not info.get('status'):
        raise ValueError('입주예정 다운로드 조회 실패')
    query = urllib.parse.urlencode({'atchFileId': info['atchFileId'], 'fileDetailSn': info['fileDetailSn'], 'insertDataPrcus': 'N'})
    with urllib.request.urlopen('https://www.data.go.kr/cmm/cmm/fileDownload.do?' + query, timeout=30) as response:
        body = response.read()
    rows = re.search(r'전체 행</strong>\s*<div[^>]*>\s*([\d,]+)', html)
    if not rows:
        raise ValueError('공식 CSV 전체 행 수를 찾지 못했습니다')
    data = parse_csv(body, asof, int(rows[1].replace(',', '')))
    data['collected'] = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime('%Y-%m-%d %H:%M KST')
    raw = ROOT / 'cache/moveins/latest.csv'
    raw.parent.mkdir(parents=True, exist_ok=True)
    if raw.exists():
        save_file(ROOT, 'moveins', 'scheduled', 'previous-asof-unknown', raw, origin='cache_import')
    raw.write_bytes(body)
    save_file(ROOT, 'moveins', 'scheduled', asof, raw)
    save_published('moveins', data, ROOT / 'cache/published/housing/moveins.json.gz', ROOT / 'data/moveins.json.gz')
    print(f'입주예정 집계: 기준 {asof}, {data["row_count"]}행, {data["total_units"]:,}호', flush=True)
    return data


if __name__ == '__main__':
    collect()
