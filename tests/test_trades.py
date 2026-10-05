"""전국 실거래 집계·누락·코드 개편·기존 캐시 회귀 검사. 외부 API를 호출하지 않는다."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import kb_trades_dashboard as dashboard
import molit_trades as collector
from trade_regions import PROVINCES, REGIONS, districts, normalize_trades, normalize_rone


def row(amount, month='2026-08', name='주택'):
    return [month + '-01', '동', name, 50, 2, amount, 2000, '', '1']


class AggregationTests(unittest.TestCase):
    def setUp(self):
        self.scope = {'서울': ['서울|종로구'], '부산': ['부산|중구']}
        self.data = {'months': ['2026-08', '2026-09'], 'trades': {
            k: {'서울|종로구': [row(10000), row(30000)],
                '부산|중구': [row(90000)]} for k in collector.TYPES}}

    def aggregate(self):
        with patch.object(dashboard, 'districts', return_value=self.scope):
            return dashboard.aggregate(self.data)

    def test_national_medians_use_transactions_not_province_medians(self):
        a = self.aggregate()['apt']
        self.assertEqual(a['서울']['price'], [20000, None])
        self.assertEqual(a['부산']['price'], [90000, None])
        self.assertEqual(a['전국']['price'], [30000, None])
        self.assertEqual(a['전국']['ppa'], [600, None])
        self.assertEqual(a['전국']['n'], [3, 0])

    def test_missing_district_is_not_zero(self):
        del self.data['trades']['apt']['부산|중구']
        a = self.aggregate()['apt']
        self.assertEqual(a['부산']['n'], [None, None])
        self.assertEqual(a['전국']['n'], [None, None])
        self.assertEqual(a['서울']['n'], [2, 0])

    def test_failed_month_invalidates_only_affected_aggregates(self):
        self.data['missing'] = {'apt': {'부산|중구': ['2026-08']}}
        a = self.aggregate()
        self.assertEqual(a['apt']['부산']['price'], [None, None])
        self.assertEqual(a['apt']['전국']['n'], [None, 0])
        self.assertEqual(a['rh']['전국']['n'], [3, 0])

    def test_legacy_seoul_cache(self):
        tr = {'trades': {k: {'종로구': [row(10000)]} for k in collector.TYPES}}
        tr = normalize_trades(tr)
        self.assertIn('서울|종로구', tr['trades']['apt'])
        self.assertEqual(tr['districts'], {'서울': ['서울|종로구']})
        self.assertEqual(normalize_trades(copy.deepcopy(tr)), tr)

    def test_low_price_list_retains_region_and_filters_month_and_type(self):
        self.data['trades']['rh']['부산|중구'] = [row(10000), row(5000, '2026-07')]
        low = dashboard.low_price_list(self.data)
        self.assertEqual(len(low), 3)
        self.assertIn(['rh', '부산|중구'] + row(10000)[:8], low)
        self.assertTrue(all(r[0] != 'apt' and r[7] <= 20000 for r in low))

    def test_region_manifest_covers_all_statistical_provinces(self):
        self.assertEqual(set(r['province'] for r in REGIONS.values()), set(PROVINCES))
        self.assertEqual(len(districts()['서울']), 25)
        self.assertEqual(len(districts()['전남']), 22)
        self.assertEqual(len(districts()['광주']), 5)
        self.assertIn('41111', REGIONS)  # 수원 장안구
        self.assertNotIn('41110', REGIONS)  # 상위 시는 중복 수집하지 않음
        self.assertIn('36110', REGIONS)


class CollectionTests(unittest.TestCase):
    def test_cache_reuse_failure_metadata_and_alias_duplicate_counts(self):
        regions = {'11110': {'province': '서울', 'district': '종로구'},
                   '11111': {'province': '서울', 'district': '종로구'},
                   '26110': {'province': '부산', 'district': '중구'}}
        scope = {'서울': ['서울|종로구'], '부산': ['부산|중구']}
        def fetch(key, kind, lawd, ym):
            if kind == 'apt' and lawd == '26110' and ym == '202609':
                raise RuntimeError('mock failure')
            return [row(10000, ym[:4] + '-' + ym[4:])] * 2
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(collector, 'ROOT', tmp), \
             patch.object(collector, 'CACHE', str(Path(tmp) / 'cache/molit')), \
             patch.object(collector, 'REGIONS', regions), \
             patch('trade_regions.REGIONS', regions), \
             patch.object(collector, 'districts', return_value=scope), \
             patch.object(collector, 'api_key', return_value='test'), \
             patch.object(collector, 'months_back', return_value=['202608', '202609']), \
             patch.object(collector, 'REFRESH_MONTHS', 1), \
             patch.object(collector, 'fetch', side_effect=fetch) as api:
            path = Path(collector.CACHE) / 'apt/11110_202608.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps([row(10000)] * 2))
            result = collector.collect(2)
            self.assertEqual(api.call_count, 17)
            self.assertEqual(len(result['trades']['apt']['서울|종로구']), 4)
            self.assertEqual(result['missing']['apt']['부산|중구'], ['2026-09'])
            self.assertEqual(result['failed'], 1)
            self.assertTrue((Path(tmp) / 'cache/trades.json').exists())


class RoneTests(unittest.TestCase):
    def test_merged_province_series_preserve_history_and_fill_complete_children(self):
        data = {'months': ['2026-06', '2026-07'], 'values': {
            '전남광주>(구)광주': [100, None],
            '전남광주>(구)전남': [200, None],
            '전남광주>동구': [10, 20], '전남광주>서구': [30, 40],
            '전남광주>목포시': [50, None], '인천>(구)중구': [1, None]}}
        scope = {'광주': ['광주|동구', '광주|서구'], '전남': ['전남|목포시']}
        with patch('trade_regions.districts', return_value=scope):
            result = normalize_rone(data)
        self.assertEqual(result['values']['광주'], [100, 60])
        self.assertEqual(result['values']['전남'], [200, None])
        self.assertEqual(result['values']['광주>동구'], [10, 20])
        self.assertEqual(result['values']['인천>중구'], [1, None])


if __name__ == '__main__':
    unittest.main()
