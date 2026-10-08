import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from market_overview import summarize, weekly_change


class OverviewTests(unittest.TestCase):
    def setUp(self):
        self.weekly = {'asof': '2026-10-05', 'dates': ['2026-08-31', '2026-09-07', '2026-09-21', '2026-09-28', '2026-10-05'],
                       'sale': {'서울특별시': [100, 101, 102, 103, 104]},
                       'jeonse': {'서울특별시': [100, 100, 100, 100, 100]}}
        self.monthly = {'asof': '2026-09', 'jeonse_ratio': {'dates': ['2026-09'], 'values': {'서울특별시': [55]}},
                        'hai': {'dates': ['2026-09'], 'values': {'서울특별시': {'apt': [80]}}}}
        self.trades = {'months': ['2026-06', '2026-07', '2026-08'], 'partial_from': '2026-09',
                       'agg': {'apt': {'서울': {'period3': {'price_n': [None, None, 20], 'price': [None, None, 50000]}}}},
                       'recovery': {'서울': {'from': '2026-06', 'to': '2026-08', 'ratio': 120, 'years': 5}}}

    def test_four_weeks_use_calendar_dates_with_holiday_gap(self):
        value, period = weekly_change(self.weekly['sale']['서울특별시'], self.weekly['dates'])
        self.assertAlmostEqual(value, (104 / 101 - 1) * 100)
        self.assertEqual(period, '2026-09-07~2026-10-05')

    def test_parent_scope_is_disclosed_and_no_price_fabricated(self):
        data = summarize(self.weekly, self.monthly, self.trades)
        district = data['metrics']['서울|종로구']
        self.assertEqual(district['price']['scope'], '서울특별시')
        self.assertEqual(district['price']['note'], '상위 지역 자료')
        self.assertIsNone(district['trade_price']['value'])
        self.assertEqual(data['metrics']['서울']['trade_price']['value'], 50000)
        self.assertIsNone(data['metrics']['부산']['price']['value'])

    def test_small_samples_suppress_price(self):
        self.trades['agg']['apt']['서울']['period3']['price_n'][2] = 9
        data = summarize(self.weekly, self.monthly, self.trades)
        self.assertIsNone(data['metrics']['서울']['trade_price']['value'])

    def test_supply_ratio_requires_matching_period_and_positive_total(self):
        supply = {'months': ['2026-07','2026-08'], 'collected': '2026-10-08 12:00 KST',
                  'values': {'서울': {'total': [100, 80], 'completed': [20, 40]}}}
        data = summarize(self.weekly, self.monthly, self.trades, supply)
        self.assertEqual(data['metrics']['서울']['supply_share']['value'], 50)
        supply['values']['서울']['total'][1] = None
        self.assertIsNone(summarize(self.weekly, self.monthly, self.trades, supply)['metrics']['서울']['supply_share']['value'])

    def test_rent_latest_period_uses_rent_collection_date_not_old_sales(self):
        self.trades['partial_from'] = '2026-07'
        rent = {'months': ['2026-07','2026-08','2026-09','2026-10'], 'collected': '2026-10-08 12:00 KST',
                'values': {'서울': {'n': [50]*4, 'deposit': [10000,20000,30000,40000], 'rent': [50,60,70,80],
                                     'jeonse_n': [25]*4, 'monthly_n': [25]*4}}}
        m = summarize(self.weekly, self.monthly, self.trades, rents=rent)['metrics']['서울']
        self.assertEqual(m['rent_deposit']['period'], '2026-08')
        self.assertEqual(m['rent_deposit']['value'], 20000)


if __name__ == '__main__':
    unittest.main()
