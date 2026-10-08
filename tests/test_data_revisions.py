import copy
import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import data_revisions as revisions


class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.before = {'schema_version': 1, 'collected': '2026-10-08 13:00 KST', 'months': ['2026-08', '2026-09'],
                       'values': {'서울': {'total': [100, 110], 'completed': [20, 30]}}}
        self.after = copy.deepcopy(self.before)
        self.after['collected'] = '2026-10-09 13:00 KST'

    def test_month_alignment_ignores_new_and_expired_months(self):
        self.after['months'] = ['2026-09', '2026-10']
        self.after['values']['서울'] = {'total': [112, 120], 'completed': [30, 40]}
        changes = revisions.changes('supply', self.before, self.after)
        self.assertEqual(len(changes), 1)
        self.assertEqual((changes[0]['month'], changes[0]['before'], changes[0]['after'], changes[0]['delta']), ('2026-09', 110, 112, 2))

    def test_missing_values_are_not_zero_or_numeric_changes(self):
        self.before['values']['서울']['total'][0] = None
        self.after['values']['서울']['total'][0] = 0
        change = revisions.changes('supply', self.before, self.after)[0]
        self.assertEqual(change['status'], '자료 보완')
        self.assertEqual(change['after'], 0)
        self.assertIsNone(change['delta'])
        reverse = revisions.changes('supply', self.after, self.before)[0]
        self.assertEqual(reverse['status'], '표시 보류')

    def test_small_price_samples_are_suppressed_and_raw_fields_are_ignored(self):
        a = {'analysis_version': 2, 'min_price_sample': 10, 'months': ['2026-08'], 'agg': {'apt': {'서울': {'n': [9], 'price_n': [9], 'price': [10000]}}}, 'low': ['private row']}
        b = copy.deepcopy(a);b['agg']['apt']['서울']['price'][0] = 20000
        self.assertEqual(revisions.changes('trades', a, b), [])
        b['agg']['apt']['서울'].update(price_n=[10], n=[10])
        result = revisions.changes('trades', a, b)
        self.assertEqual(len(result), 2)
        self.assertNotIn('private', json.dumps(result))
        self.assertEqual(next(c for c in result if c['unit'] == '만원')['status'], '자료 보완')

    def test_baseline_and_unchanged_checks_do_not_fabricate_revisions(self):
        first = revisions.history('supply', self.before, observed_at='2026-10-08 15:00 KST')
        self.before['revision_history'] = first
        checked = revisions.history('supply', self.after, self.before, '2026-10-09 15:00 KST')
        self.assertEqual(checked['events'], [])
        self.assertEqual(checked['tracking_since'], '2026-10-08 15:00 KST')
        self.assertEqual(checked['last_collected'], self.after['collected'])
        self.assertEqual(first['last_checked'], '2026-10-08 15:00 KST')

    def test_incompatible_schema_starts_a_new_baseline(self):
        self.after['schema_version'] = 2
        self.after['values']['서울']['total'][0] = 200
        result = revisions.history('supply', self.after, self.before, '2026-10-09 15:00 KST')
        self.assertEqual(result['events'], [])
        self.assertEqual(result['tracking_since'], '2026-10-09 15:00 KST')

    def test_preserves_dates_and_history_across_identical_rebuild(self):
        self.after['values']['서울']['completed'][0] = 10
        self.after['revision_history'] = revisions.history('supply', self.after, self.before, '2026-10-09 15:00 KST')
        again = revisions.history('supply', self.after, self.after, '2026-10-10 15:00 KST')
        self.assertEqual(len(again['events']), 1)
        event = again['events'][0]
        self.assertEqual(event['before_collected'], self.before['collected'])
        self.assertEqual(event['after_collected'], self.after['collected'])
        self.assertEqual(event['changes'][0]['delta'], -10)
        self.assertEqual(self.after['revision_history']['last_checked'], '2026-10-09 15:00 KST')

    def test_retention_limits_keep_latest_and_report_omissions(self):
        prior = self.before
        with patch.object(revisions, 'EVENT_LIMIT', 2), patch.object(revisions, 'CHANGE_LIMIT', 2):
            for day in range(9, 13):
                current = copy.deepcopy(prior);current['collected'] = f'2026-10-{day:02d} 13:00 KST'
                current['values']['서울']['total'] = [100 + day, 110 + day]
                current['revision_history'] = revisions.history('supply', current, prior)
                prior = current
        info = prior['revision_history']
        self.assertEqual(len(info['events']), 2)
        self.assertEqual(sum(len(e['changes']) for e in info['events']), 2)
        self.assertEqual(info['dropped_events'], 2)
        self.assertEqual(info['dropped_changes'], 6)
        self.assertEqual(info['events'][-1]['after_collected'], '2026-10-12 13:00 KST')

    def test_complete_latest_baseline_and_atomic_save_reject_failed_or_older_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache, seed = Path(tmp)/'cache.json.gz', Path(tmp)/'seed.json.gz'
            revisions.save_published('supply', self.before, seed)
            self.after['values']['서울']['completed'][1] = 35
            revisions.save_published('supply', self.after, cache, seed)
            data = json.loads(gzip.decompress(cache.read_bytes()))
            self.assertEqual(len(data['revision_history']['events']), 1)
            self.assertEqual(data['revision_history']['events'][0]['changes'][0]['delta'], 5)
            saved = cache.read_bytes()
            bad = copy.deepcopy(self.after);bad['failed'] = 1
            with self.assertRaises(ValueError):revisions.save_published('supply', bad, cache, seed)
            with self.assertRaises(ValueError):revisions.save_published('supply', self.before, cache, seed)
            self.assertEqual(saved, cache.read_bytes())
            self.assertFalse(cache.with_suffix('.part').exists())
            cache.write_bytes(b'invalid gzip')
            self.assertEqual(revisions.baseline('supply', [cache, seed], self.after)['collected'], self.before['collected'])

    def test_tied_baselines_prefer_registered_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp)/'a.gz', Path(tmp)/'b.gz'
            a.write_bytes(gzip.compress(json.dumps(self.before).encode()))
            revisions.save_published('supply', self.before, b)
            self.assertIn('revision_history', revisions.baseline('supply', [a,b], self.after))


if __name__ == '__main__':
    unittest.main()
