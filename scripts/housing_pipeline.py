"""공식 아파트 인허가·착공·준공 월계 실적을 추출한다. 예정 입주량으로 환산하지 않는다."""
import datetime as dt
from pathlib import Path
import re
import urllib.parse
import urllib.request

from data_revisions import save_published
from data_archive import save_file
from trade_regions import PROVINCES

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {'permit': (31, '인허가'), 'start': (471, '착공'), 'completion': (468, '준공')}


def norm(value):
    return re.sub(r'\s+', '', str(value or '')).replace('*', '')


def parse_rows(rows, month, label):
    text = ' '.join(str(cell) for row in rows[:6] for cell in row)
    if label not in text:
        raise ValueError('주택건설 단계가 파일 설명과 다릅니다')
    header = next((i for i, row in enumerate(rows[:8]) if any(norm(c) == '<월계>' for c in row)), None)
    if header is None:
        raise ValueError('월계 표를 찾지 못했습니다')
    offset = next(j for j, cell in enumerate(rows[header]) if norm(cell) == '<월계>')
    block = ' '.join(str(c) for c in rows[header][offset:offset+9])
    date = re.search(r'(\d{4})년\s*(\d{1,2})월', block)
    if not date or f'{date[1]}-{int(date[2]):02d}' != month:
        raise ValueError('월계 기준월이 파일 날짜와 다릅니다')
    columns = next((row for row in rows[header+1:header+4] if len(row) > offset+8 and norm(row[offset+8]) == '아파트'), None)
    if columns is None:
        raise ValueError('아파트 열을 찾지 못했습니다')
    result = {}
    for row in rows[header+2:]:
        if len(row) <= offset+8:
            continue
        name = norm(row[offset])
        key = '전국' if name in ('계', '총계', '전국') else name
        if key not in PROVINCES + ['전국', '전남광주']:
            continue
        value = row[offset+8]
        if not isinstance(value, (int, float)) or value < 0 or int(value) != value:
            raise ValueError('아파트 월계 실적이 올바르지 않습니다')
        if key in result:
            raise ValueError('월계에 지역이 중복됩니다')
        result[key] = int(value)
    needed = set(PROVINCES)
    if '전남광주' in result:
        if '광주' in result or '전남' in result:
            raise ValueError('통합 권역과 기존 권역이 중복됩니다')
        needed -= {'광주', '전남'}
        needed.add('전남광주')
    if not needed.issubset(result) or '전국' not in result or sum(result[k] for k in needed) != result['전국']:
        raise ValueError('아파트 월계 전국·시도 합계가 맞지 않습니다')
    if '전남광주' not in result:
        result['전남광주'] = result['광주'] + result['전남']
    return result


def parse_workbook(body, month, label):
    import xlrd
    book = xlrd.open_workbook(file_contents=body)
    try:
        sheet = next(s for s in book.sheets() if '주택유형별' in s.name and '다가구구분' in s.name)
        return parse_rows([sheet.row_values(i) for i in range(sheet.nrows)], month, label)
    finally:
        book.release_resources()


def collect(limit=6):
    stages = {}
    for kind, (rs, label) in SOURCES.items():
        source = f'https://stat.molit.go.kr/portal/cate/statMetaView.do?hRsId={rs}'
        with urllib.request.urlopen(source, timeout=30) as response:
            html = response.read().decode('utf-8')
        files = {}
        for name, filename, folder in re.findall(r"downFile\('([^']+)','([^']+)','([^']+)'", html):
            date = re.match(r'(\d{2,4})년\s*(\d{1,2})월\s*' + label + r'실적.*\.xls$', name)
            if date:
                year = int(date[1]);year = year + 2000 if year < 100 else year
                files[f'{year:04d}-{int(date[2]):02d}'] = (name, filename, folder)
        if not files:
            raise ValueError('공식 월별 주택건설 파일을 찾지 못했습니다')
        periods = {}
        for month in sorted(files, reverse=True)[:limit]:
            query = urllib.parse.urlencode(dict(zip(('oFileName','rFileName','midpath'), files[month])))
            with urllib.request.urlopen('https://stat.molit.go.kr/portal/common/downLoadFile.do?' + query, timeout=30) as response:
                body = response.read()
            periods[month] = parse_workbook(body, month, label)
            raw = ROOT / 'cache/pipeline' / (kind + '_' + month + '.xls')
            raw.parent.mkdir(parents=True, exist_ok=True)
            if raw.exists():
                save_file(ROOT, 'pipeline', kind, month, raw, origin='cache_import')
            raw.write_bytes(body)
            save_file(ROOT, 'pipeline', kind, month, raw)
            print('아파트 공급 실적:', label, month, periods[month]['전국'], flush=True)
        stages[kind] = periods
    months = sorted(set.intersection(*(set(v) for v in stages.values())))
    if len(months) < limit:
        raise ValueError('인허가·착공·준공의 공통 월이 부족합니다')
    keys = ['전국'] + PROVINCES + ['전남광주']
    data = {'schema_version': 1, 'months': months,
            'collected': dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime('%Y-%m-%d %H:%M KST'),
            'values': {key: {kind: [stages[kind][m].get(key) for m in months] for kind in stages} for key in keys},
            'sources': {k: f'https://stat.molit.go.kr/portal/cate/statMetaView.do?hRsId={v[0]}' for k,v in SOURCES.items()},
            'basis': '아파트 월계 실적 · 미래 입주·순증 주택 수 아님'}
    save_published('pipeline', data, ROOT / 'cache/published/housing/pipeline.json.gz', ROOT / 'data/pipeline.json.gz')
    return data


if __name__ == '__main__':
    collect()
