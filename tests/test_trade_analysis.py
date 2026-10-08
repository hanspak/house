"""가격 구성·기간 중위값·결측 전파·계절 비교의 분석 회귀 검사."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from trade_analysis import aggregate_profiles, trade_recovery


def row(month, amount, area=60, built=2021):
    return [month + '-01', '동', '건물', area, 2, amount, built, '', '1']


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.months = ['2026-06', '2026-07', '2026-08']
        self.scope = {'서울': ['서울|종로구']}
        self.tr = {'months': self.months, 'collected': '2026-10-06 01:46 KST',
                   'trades': {'apt': {'서울|종로구': [row('2026-06', 10000)] * 100 +
                                                     [row('2026-07', 20000), row('2026-08', 30000)]}}}

    def test_three_month_median_pools_transactions_not_monthly_medians(self):
        data = aggregate_profiles(self.tr, self.scope)['all-all']['apt']['전국']
        self.assertEqual(data['price'], [10000, 20000, 30000])
        self.assertEqual(data['period3']['price'], [None, None, 10000])
        self.assertEqual(data['period3']['n'], [None, None, 102])
        self.assertEqual(data['period3']['q1'][2], 10000)
        self.assertEqual(data['period3']['q3'][2], 10000)

    def test_filters_use_area_boundaries_collection_year_and_unknown_exclusion(self):
        self.tr['trades']['apt']['서울|종로구'] = [
            row('2026-08', 10000, 60, 2021), row('2026-08', 20000, 85, 2006),
            row('2026-08', 30000, 86, 2005), row('2026-08', 40000, 0, 0)]
        profiles = aggregate_profiles(self.tr, self.scope)
        for profile in ['small-new', 'medium-middle', 'large-old']:
            self.assertEqual(profiles[profile]['apt']['전국']['n'][2], 1)
        all_ = profiles['all-all']['apt']['전국']
        self.assertEqual(all_['n'][2], 4)
        self.assertEqual(all_['price_n'][2], 4)
        self.assertEqual(all_['ppa_n'][2], 3)

    def test_missing_month_propagates_even_for_empty_filter(self):
        self.tr['missing'] = {'apt': {'서울|종로구': ['2026-07']}}
        profiles = aggregate_profiles(self.tr, self.scope)
        data = profiles['large-old']['apt']['전국']
        self.assertEqual(data['n'], [0, None, 0])
        self.assertIsNone(data['period3']['n'][2])
        self.assertIsNone(data['period3']['price'][2])

    def test_recovery_compares_same_season_and_requires_complete_periods(self):
        months = [f'{y}-{m:02d}' for y in range(2021, 2027) for m in range(1, 13)]
        values = [200 if m.startswith('2026') else 100 for m in months]
        series = {'months': months, 'values': {'전국': values}}
        data = trade_recovery(series, '2026-09')['전국']
        self.assertEqual((data['from'], data['to']), ('2026-06', '2026-08'))
        self.assertEqual(data['n'], 600)
        self.assertEqual(data['baseline'], 300)
        self.assertEqual(data['ratio'], 200)
        self.assertEqual(data['years'], 5)
        for year in (2021, 2022, 2023):
            values[months.index(f'{year}-07')] = None
        data = trade_recovery(series, '2026-09')['전국']
        self.assertEqual(data['years'], 2)
        self.assertIsNone(data['ratio'])

    def test_zero_baseline_is_not_infinite_and_missing_current_is_not_zero(self):
        months = [f'{y}-{m:02d}' for y in range(2021, 2027) for m in range(1, 13)]
        values = [0] * len(months)
        data = trade_recovery({'months': months, 'values': {'전국': values}}, '2026-09')['전국']
        self.assertIsNone(data['ratio'])
        values[months.index('2026-07')] = None
        data = trade_recovery({'months': months, 'values': {'전국': values}}, '2026-09')['전국']
        self.assertIsNone(data['n'])


if __name__ == '__main__':
    unittest.main()
