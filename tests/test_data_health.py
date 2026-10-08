import datetime as dt
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from data_health import assess, report, kst_today
from market_overview import summarize
import kb_status


class HealthTests(unittest.TestCase):
    today = dt.date(2026, 10, 8)

    def source(self, **kw):
        return {'kind': 'monthly', 'period': '2026-08', 'collected': '2026-10-08 01:00 KST', **kw}

    def test_weekly_boundary_and_unknown_collection_are_separate(self):
        a = assess(self.source(kind='weekly', period='2026-09-24', collected=None), self.today)
        self.assertEqual(a['status'], 'within')
        self.assertIn('수집일 기록 없음', a['note'])
        b = assess(self.source(kind='weekly', period='2026-09-23'), self.today)
        self.assertEqual(b['status'], 'review')
        self.assertEqual(b['period_age'], 15)

    def test_monthly_boundary_and_year_rollover(self):
        self.assertEqual(assess(self.source(), self.today)['status'], 'within')
        self.assertEqual(assess(self.source(period='2026-07'), self.today)['status'], 'review')
        self.assertEqual(assess(self.source(period='2026-11'), self.today)['status'], 'review')
        a = assess(self.source(period='2025-11', collected='2026-01-08'), dt.date(2026, 1, 8))
        self.assertEqual(a['period_age'], 2)
        self.assertEqual(a['status'], 'within')

    def test_recent_period_does_not_hide_old_collection(self):
        self.assertEqual(assess(self.source(collected='2026-10-05'), self.today)['status'], 'within')
        a = assess(self.source(period='2026-10', collected='2026-10-04'), self.today)
        self.assertEqual(a['status'], 'review')
        self.assertEqual(a['collection_age_days'], 4)
        self.assertEqual(assess(self.source(collected='2026-10-09'), self.today)['status'], 'review')

    def test_forecast_uses_coverage_not_future_scheduled_month_as_observation(self):
        source = self.source(kind='forecast', asof='2026-06-30', period='2026-07~2028-06 · 기준 2026-06-30', horizon_start='2026-07', horizon_end='2028-06')
        self.assertEqual(assess(source, self.today)['status'], 'within')
        self.assertEqual(assess({**source, 'horizon_end': '2026-12'}, self.today)['status'], 'review')
        self.assertEqual(assess({**source, 'horizon_start': '2026-11'}, self.today)['status'], 'review')
        self.assertEqual(assess({**source, 'collected': None}, self.today)['status'], 'review')

    def test_missing_malformed_and_future_dates_do_not_crash_or_pass(self):
        for period in [None, '', '2026-13', 'invalid', '2026-08-01']:
            self.assertEqual(assess(self.source(period=period), self.today)['status'], 'review')
        for period in [None, '2026-02-30', '2026-10-09']:
            self.assertEqual(assess(self.source(kind='weekly', period=period), self.today)['status'], 'review')

    def test_report_is_explicit_and_does_not_mutate_source(self):
        source = self.source(name='sample')
        data = report([source, self.source(kind='weekly', period=None)], self.today)
        self.assertEqual(data['review_count'], 1)
        self.assertEqual(data['checked_on'], '2026-10-08')
        self.assertNotIn('health', source)
        self.assertIn('운영 기준', data['policy'])

    def test_kst_day_used_by_actions_without_relying_on_host_timezone(self):
        self.assertEqual(kst_today(dt.datetime(2026, 10, 7, 16, tzinfo=dt.timezone.utc)), self.today)
        with patch.object(kb_status, 'kst_today', return_value=self.today), patch.object(kb_status.os.path, 'exists', return_value=False):
            self.assertIn('주간 자료 기준일 기록 없음', kb_status.check())

    def test_unavailable_feeds_are_reported_in_overview(self):
        data = summarize({'dates': []}, {}, {'months': [], 'partial_from': '2026-09'}, today=self.today)
        sources = {s['name']: s for s in data['sources']}
        self.assertEqual(sources['국토부 공식 미분양']['health']['status'], 'review')
        self.assertEqual(sources['공동주택 입주예정']['health']['status'], 'review')
        self.assertEqual(data['health']['checked_on'], '2026-10-08')


if __name__ == '__main__':
    unittest.main()
