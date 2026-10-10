import contextlib
import gzip
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import collection_runs as runs
import market_extra as extra
import kb_trades_dashboard as dashboard
from trade_regions import PROVINCES
from trade_analysis import source_dates


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / 'cache/published/collection-status/rates.json'

    def invoke(self, side=None, code=0, result=None):
        with patch.object(runs.subprocess, 'run', return_value=subprocess.CompletedProcess([], code), side_effect=side), contextlib.redirect_stdout(io.StringIO()):
            return runs.execute(self.root, 'rates', ['python', 'secret-query'], 2, result)

    def test_failure_retains_success_and_excludes_arguments(self):
        self.assertEqual(self.invoke(), 0)
        success = runs.read(self.path)['last_success']
        self.assertNotEqual(self.invoke(code=1), 0)
        data = runs.read(self.path)
        self.assertEqual(data['last_success'], success)
        self.assertEqual(data['last_attempt']['status'], 'failure')
        self.assertNotIn('secret-query', self.path.read_text())

    def test_timeout_and_interrupt(self):
        for error, status in [(subprocess.TimeoutExpired(['secret'], 2), 'timeout'), (KeyboardInterrupt(), 'interrupted')]:
            self.assertNotEqual(self.invoke(side=error), 0)
            self.assertEqual(runs.read(self.path)['last_attempt']['status'], status)
            self.assertNotIn('last_success', runs.read(self.path))

    def test_partial_and_missing_result_are_not_success(self):
        p = self.root / 'result.json'
        p.write_text(json.dumps({'failed': 3}))
        self.assertNotEqual(self.invoke(result='result.json'), 0)
        self.assertEqual(runs.read(self.path)['last_attempt']['status'], 'partial')
        p.unlink()
        self.assertNotEqual(self.invoke(result='result.json'), 0)
        self.assertNotIn('last_success', runs.read(self.path))

    def test_history_limit_and_running_record(self):
        def check(*args, **kwargs):
            self.assertEqual(runs.read(self.path)['last_attempt']['status'], 'running')
            return subprocess.CompletedProcess([], 0)
        with patch.object(runs.subprocess, 'run', side_effect=check), contextlib.redirect_stdout(io.StringIO()):
            for _ in range(32):
                runs.execute(self.root, 'rates', ['python'], 2)
        self.assertEqual(len(runs.read(self.path)['events']), 30)
        self.assertEqual(len(runs.summary(self.root)), len(runs.NAMES))

    def seed(self):
        feed = {'months': ['2026-08'], 'values': {'region': [1]}, 'source': 'test'}
        p = self.root / 'data/trades.json.gz'
        p.parent.mkdir()
        p.write_bytes(gzip.compress(json.dumps({'extra': {'collected': '2026-10-01 01:00 KST', 'apt_trades': feed, 'unsold': feed, 'rates': feed}}).encode()))
        return feed

    def test_independent_failure_keeps_old_feeds_and_dates(self):
        feed = self.seed()
        with patch.object(extra, 'ROOT', str(self.root)), patch.object(extra, 'keys', return_value=('key', 'key')), patch.object(extra, 'rone_apt_trades', side_effect=RuntimeError('secret-body')), patch.object(extra, 'rone_unsold', return_value=feed.copy()), patch.object(extra, 'ecos_rates', return_value=feed.copy()), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(extra.main(), 1)
        data = extra.load_extra(self.root)
        self.assertEqual(data['apt_trades']['collected'], '2026-10-01 01:00 KST')
        self.assertGreater(data['rates']['collected'], data['apt_trades']['collected'])
        self.assertNotIn('secret-body', output.getvalue())
        sources = source_dates({'months': ['2026-10'], 'collected': 'old', 'extra': data})
        self.assertEqual(sources[1]['collected'], data['apt_trades']['collected'])
        self.assertEqual(sources[3]['collected'], data['rates']['collected'])

    def test_missing_keys_and_empty_feed_do_not_replace_previous(self):
        self.seed()
        with patch.object(extra, 'ROOT', str(self.root)), patch.object(extra, 'keys', return_value=(None, None)), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(extra.main(), 1)
        before = extra.load_extra(self.root)
        with patch.object(extra, 'ROOT', str(self.root)), patch.object(extra, 'keys', return_value=('key', 'key')), patch.object(extra, 'ecos_rates', return_value={'months': [], 'values': {}}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(extra.main('rates'), 1)
        self.assertEqual(extra.load_extra(self.root), before)

    def test_selected_feed_does_not_call_other_sources(self):
        feed = self.seed()
        with patch.object(extra, 'ROOT', str(self.root)), patch.object(extra, 'keys', return_value=('key', 'key')), patch.object(extra, 'rone_apt_trades') as apt, patch.object(extra, 'rone_unsold') as unsold, patch.object(extra, 'ecos_rates', return_value=feed.copy()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(extra.main('rates'), 0)
        apt.assert_not_called()
        unsold.assert_not_called()

    def test_extra_update_reaches_snapshot_without_new_trades(self):
        feed = self.seed()
        path = self.root / 'data/trades.json.gz'
        with gzip.open(path, 'rt') as f:
            snapshot = json.load(f)
        snapshot.update(months=['2026-08'], collected='2026-10-01 00:00 KST', failed=0,
                        provinces=PROVINCES, analysis_version=dashboard.ANALYSIS_VERSION,
                        partial_from='2026-09', agg={'apt': {'region': {'n': [12]}}})
        path.write_bytes(gzip.compress(json.dumps(snapshot).encode()))
        runs.write(self.root / 'cache/published/extra/rates.json',
                   {**feed, 'collected': '2026-10-09 00:00 KST', 'values': {'region': [3]}})
        with patch.object(dashboard, 'ROOT', str(self.root)), patch.object(dashboard, 'render', side_effect=lambda d: d):
            result = dashboard.build_snapshot()
        self.assertEqual(result['collected'], snapshot['collected'])
        self.assertEqual(result['agg'], snapshot['agg'])
        self.assertEqual(result['extra']['rates']['values']['region'], [3])
        self.assertEqual(result['sources'][-1]['collected'], '2026-10-09 00:00 KST')

    def test_corrupt_cache_and_invalid_feed_use_baseline(self):
        self.seed()
        p = self.root / 'cache/extra.json'
        p.parent.mkdir(parents=True)
        p.write_text('{broken')
        runs.write(self.root / 'cache/published/extra/rates.json',
                   {'months': ['2026-09'], 'values': {'region': ['bad']}})
        with contextlib.redirect_stdout(io.StringIO()):
            result = extra.load_extra(self.root)
        self.assertEqual(result['rates']['values']['region'], [1])
        self.assertEqual(result['rates']['collected'], '2026-10-01 01:00 KST')

    def test_subprocess_timeout_is_recorded(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertNotEqual(runs.execute(self.root, 'rates',
                [sys.executable, '-c', 'import time; time.sleep(2)'], .05), 0)
        self.assertEqual(runs.read(self.path)['last_attempt']['status'], 'timeout')


if __name__ == '__main__':
    unittest.main()
