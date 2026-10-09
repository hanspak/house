import gzip
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch
import contextlib
import io

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import data_archive as archive
import molit_trades as trades


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.row = ['2026-08-01', 'dong', 'name', 50, 2, 10000, 2000, '', '1']

    def save(self, rows=None, **kw):
        return archive.save_rows(self.root, 'trades', 'apt', '11110', '202608', [self.row] if rows is None else rows, **kw)

    def query(self, sql):
        with sqlite3.connect(self.root / 'storage/trades/archive.sqlite3') as c:
            return c.execute(sql).fetchall()

    def test_versions_preserve_identical_transactions_and_empty_response(self):
        first = self.save([self.row, self.row])
        self.save([self.row, self.row])
        self.save([])
        later = self.row.copy()
        later[5] = 12000
        self.save([later])
        data = archive.inventory(self.root)['trades']
        self.assertEqual(data['snapshots'], 3)
        self.assertEqual(data['records'], 3)
        self.assertEqual(data['observations'], 4)
        blob = self.root / 'storage/trades/blobs' / (first + '.gz')
        self.assertEqual(json.loads(gzip.decompress(blob.read_bytes())), [self.row, self.row])
        self.assertEqual(archive.verify(self.root / 'storage'), 3)

    def test_cache_migration_is_idempotent_and_does_not_infer_api_time(self):
        p = self.root / 'cache/molit/apt/11110_202608.json'
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps([self.row]))
        before = p.read_bytes()
        archive.import_cache(self.root, self.root / 'cache')
        archive.import_cache(self.root, self.root / 'cache')
        self.assertEqual(p.read_bytes(), before)
        self.assertEqual(archive.inventory(self.root)['trades']['observations'], 1)
        self.assertEqual(self.query('SELECT origin FROM observations'), [('cache_import',)])
        self.assertTrue(self.query('SELECT source_modified_at FROM observations')[0][0])

    def test_region_alias_codes_are_separate_not_globally_deduplicated(self):
        self.save()
        archive.save_rows(self.root, 'trades', 'apt', '11111', '202608', [self.row])
        self.assertEqual(archive.inventory(self.root)['trades']['records'], 2)

    def test_invalid_scope_rows_and_nonfinite_are_rejected(self):
        for rows in [[self.row[:-1]], [['2026-07-01'] + self.row[1:]], [[self.row[0], {}] + self.row[2:]], [[self.row[0], float('nan')] + self.row[2:]]]:
            with self.assertRaises((ValueError, TypeError)):
                self.save(rows)
        with self.assertRaises(ValueError):
            archive.save_rows(self.root, 'trades', 'apt', '../x', '202608', [])
        self.assertEqual(archive.inventory(self.root), {})

    def test_concurrent_writers_do_not_lose_observations(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda i: self.save(observation_key=str(i)), range(12)))
        data = archive.inventory(self.root)['trades']
        self.assertEqual(data['snapshots'], 1)
        self.assertEqual(data['records'], 1)
        self.assertEqual(data['observations'], 12)

    def test_backup_is_restorable_and_corruption_is_detected(self):
        self.save([self.row, self.row])
        dest = self.root / 'backup'
        archive.backup(self.root, dest)
        self.assertEqual(archive.verify(dest), 1)
        with sqlite3.connect(dest / 'trades/archive.sqlite3') as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM records').fetchone()[0], 2)
        with self.assertRaises(ValueError):
            archive.backup(self.root, dest)
        blob = next((dest / 'trades/blobs').glob('*.gz'))
        blob.write_bytes(gzip.compress(b'corrupt'))
        with self.assertRaises(ValueError):
            archive.verify(dest)

    def test_rents_and_download_files_have_separate_databases(self):
        row = ['2026-08-01', 30000, 0, 50, 'new', 'id', 'apt', '1', '2', 'dong', '2000']
        archive.save_rows(self.root, 'rents', 'apt', '11110', '202608', [row])
        p = self.root / 'source.csv'
        p.write_bytes(b'original CSV')
        archive.save_file(self.root, 'moveins', 'scheduled', '2026-06-30', p)
        archive.save_file(self.root, 'moveins', 'scheduled', '2026-06-30', p)
        status = archive.inventory(self.root)
        self.assertEqual(status['rents']['records'], 1)
        self.assertEqual(status['moveins']['snapshots'], 1)
        self.assertEqual(status['moveins']['observations'], 2)

    def test_archive_failure_does_not_replace_previous_trade_cache(self):
        cache = self.root / 'cache/molit'
        path = cache / 'apt/11110_202608.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps([self.row]))
        before = path.read_bytes()
        newer = self.row.copy()
        newer[5] = 12000
        with patch.object(trades, 'ROOT', str(self.root)), patch.object(trades, 'CACHE', str(cache)), patch.object(trades, 'REGIONS', {'11110': {}}), patch.object(trades, 'TYPES', {'apt': trades.TYPES['apt']}), patch.object(trades, 'months_back', return_value=['202608']), patch.object(trades, 'api_key', return_value='test'), patch.object(trades, 'fetch', return_value=[newer]), patch.object(trades, 'save_rows', side_effect=OSError('disk full')), contextlib.redirect_stdout(io.StringIO()):
            result = trades.collect(1, 1)
        self.assertEqual(result['failed'], 1)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(archive.inventory(self.root)['trades']['records'], 1)


if __name__ == '__main__':
    unittest.main()
