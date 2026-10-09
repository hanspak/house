"""전국 아파트 전월세 월별 캐시와 게시용 집계. 원거래·인증키는 게시하지 않는다."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import json
from pathlib import Path
import statistics
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from molit_trades import api_key, months_back, pace
from data_revisions import save_published
from trade_regions import REGIONS, districts, region_id
from data_archive import save_rows, save_cached_rows

ROOT = Path(__file__).resolve().parents[1]


def parse_items(root):
    rows = []
    for item in root.findall('.//item'):
        f = {child.tag: (child.text or '').strip() for child in item}
        if f.get('cdealType') == 'O':
            continue
        try:
            deposit = int(f['deposit'].replace(',', ''))
            rent = int(f['monthlyRent'].replace(',', ''))
            area = float(f['excluUseAr'])
            date = dt.date(int(f['dealYear']), int(f['dealMonth']), int(f['dealDay'])).isoformat()
        except (KeyError, ValueError):
            continue
        rows.append([date, deposit, rent, area, f.get('contractType', ''),
                     f.get('aptSeq', ''), f.get('aptNm', ''), f.get('jibun', ''),
                     f.get('floor', ''), f.get('umdNm', ''), f.get('buildYear', '')])
    return rows


def fetch(key, code, month):
    page, rows = 1, []
    while True:
        query = urllib.parse.urlencode({'serviceKey': key, 'LAWD_CD': code, 'DEAL_YMD': month,
                                        'pageNo': page, 'numOfRows': 1000})
        url = 'https://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent?' + query
        for attempt in range(2):
            try:
                pace('apt-rent')
                with urllib.request.urlopen(url, timeout=30) as response:
                    root = ET.fromstring(response.read())
                if root.findtext('.//resultCode') not in ('000', '00'):
                    raise RuntimeError('아파트 전월세 API 응답 실패')
                break
            except Exception:
                if attempt == 1:
                    raise
                time.sleep(3)
        rows.extend(parse_items(root))
        if page * 1000 >= int(root.findtext('.//totalCount') or 0):
            return rows
        page += 1


def aggregate(months, by_region, missing):
    scope = districts()
    groups = {g: [g] for ids in scope.values() for g in ids}
    groups.update(scope)
    groups['전국'] = [g for ids in scope.values() for g in ids]
    result = {}
    for region, ids in groups.items():
        rows = [row for g in ids for row in by_region.get(g, [])]
        absent = {m for g in ids for m in missing.get(g, [])}
        if any(g not in by_region for g in ids):
            absent.update(months)
        series = {key: [] for key in ('n', 'jeonse_n', 'monthly_n', 'deposit', 'rent', 'new_n', 'renewal_n', 'unknown_n')}
        for month in months:
            selected = [r for r in rows if r[0][:7] == month]
            jeonse = [r[1] for r in selected if r[2] == 0 and r[1] > 0]
            monthly = [r[2] for r in selected if r[2] > 0]
            median = lambda xs: round(statistics.median(xs), 1) if len(xs) >= 10 else None
            values = {'n': len(selected), 'jeonse_n': len(jeonse), 'monthly_n': len(monthly),
                      'deposit': median(jeonse), 'rent': median(monthly),
                      'new_n': sum(r[4] == '신규' for r in selected),
                      'renewal_n': sum(r[4] == '갱신' for r in selected),
                      'unknown_n': sum(r[4] not in ('신규', '갱신') for r in selected)}
            for key, value in values.items():
                series[key].append(None if month in absent else value)
        result[region] = series
    return result


def collect(months=6, workers=8):
    key = api_key()
    yms = months_back(months)
    jobs = [(code, month) for code in REGIONS for month in yms]
    by_region = {region_id(code): [] for code in REGIONS}
    missing, counters, failures = {}, {}, 0
    def one(job):
        code, month = job
        path = ROOT / 'cache/molit-rents' / f'{code}_{month}.json'
        try:
            if month not in yms[-3:] and path.exists():
                rows = json.loads(path.read_text())
                save_cached_rows(ROOT, 'rents', 'apt', code, month, rows, path)
                return job, rows
            if path.exists():
                save_cached_rows(ROOT, 'rents', 'apt', code, month, json.loads(path.read_text()), path)
            rows = fetch(key, code, month)
            save_rows(ROOT, 'rents', 'apt', code, month, rows)
            path.parent.mkdir(parents=True, exist_ok=True)
            part = path.with_suffix('.part')
            part.write_text(json.dumps(rows, ensure_ascii=False))
            part.replace(path)
            return job, rows
        except Exception as error:
            return job, None
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for i, ((code, month), rows) in enumerate(executor.map(one, jobs), 1):
            region = region_id(code)
            if rows is None:
                failures += 1
                missing.setdefault(region, []).append(f'{month[:4]}-{month[4:]}')
            else:
                seen = counters.setdefault(region, Counter())
                batch = Counter(tuple(r) for r in rows)
                for row, n in batch.items():
                    by_region[region].extend([list(row)] * max(0, n - seen[row]))
                    seen[row] = max(seen[row], n)
            if i % 100 == 0:
                print(f'전월세 수집 {i}/{len(jobs)} · 실패 {failures}', flush=True)
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))
    ms = [f'{m[:4]}-{m[4:]}' for m in yms]
    data = {'schema_version': 1, 'months': ms, 'collected': now.strftime('%Y-%m-%d %H:%M KST'),
            'failed': failures, 'values': aggregate(ms, by_region, missing),
            'source': '국토교통부 아파트 전월세 실거래가 API', 'min_sample': 10}
    # 불완전한 집계도 별도 캐시에 남기되 마지막 완전한 게시 자료는 덮어쓰지 않는다.
    dest = ROOT / 'cache/rents.json'
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')))
    if not failures:
        dest = ROOT / 'cache/published/housing/rents.json.gz'
        save_published('rents', data, dest, ROOT / 'data/rents.json.gz')
    print(f'전월세 집계 완료 · 실패 {failures} · 완전한 자료만 게시용으로 보존', flush=True)
    return data


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--months', type=int, default=6)
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    if args.months < 1 or args.workers < 1:
        parser.error('months와 workers는 1 이상이어야 합니다')
    collect(args.months, args.workers)
