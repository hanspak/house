"""Local versioned archives and SQLite inventory; never published by Pages."""
import argparse
from contextlib import closing
import datetime as dt
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ('trades', 'rents', 'supply', 'pipeline', 'moveins', 'extra')
SCHEMA = '''
CREATE TABLE IF NOT EXISTS snapshots (
 id INTEGER PRIMARY KEY, kind TEXT NOT NULL, region_code TEXT NOT NULL,
 period TEXT NOT NULL, sha256 TEXT NOT NULL, format TEXT NOT NULL,
 row_count INTEGER, UNIQUE(kind, region_code, period, sha256));
CREATE TABLE IF NOT EXISTS records (
 snapshot_id INTEGER NOT NULL REFERENCES snapshots(id), ordinal INTEGER NOT NULL,
 contract_date TEXT NOT NULL, payload_json TEXT NOT NULL,
 PRIMARY KEY(snapshot_id, ordinal));
CREATE INDEX IF NOT EXISTS records_date ON records(contract_date);
CREATE TABLE IF NOT EXISTS observations (
 id INTEGER PRIMARY KEY, snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
 observed_at TEXT NOT NULL, origin TEXT NOT NULL, observation_key TEXT NOT NULL,
 source_modified_at TEXT,
 UNIQUE(snapshot_id, origin, observation_key));
PRAGMA user_version=1;
'''


def now():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(timespec='microseconds')


def folder(root, source):
    if source not in SOURCES:
        raise ValueError('Unsupported archive source')
    path = Path(root) / 'storage' / source
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def record(root, source, kind, region_code, period, body, fmt, rows=None,
           origin='api', observation_key=None, modified=None):
    if origin not in ('api', 'download', 'cache_import'):
        raise ValueError('Unsupported observation origin')
    observed = now()
    key = observation_key or observed
    base = folder(root, source)
    digest = hashlib.sha256(body).hexdigest()
    with (base / 'write.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        blobs = base / 'blobs'
        blobs.mkdir(exist_ok=True, mode=0o700)
        blob = blobs / (digest + '.gz')
        if blob.exists():
            if hashlib.sha256(gzip.decompress(blob.read_bytes())).hexdigest() != digest:
                raise ValueError('Archive checksum mismatch')
        else:
            fd, temporary = tempfile.mkstemp(dir=blobs, suffix='.part')
            try:
                with os.fdopen(fd, 'wb') as f:
                    f.write(gzip.compress(body, mtime=0))
                os.replace(temporary, blob)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        db = base / 'archive.sqlite3'
        with closing(sqlite3.connect(db, timeout=60)) as connection:
            version = connection.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                raise ValueError('Unsupported archive database schema')
            connection.execute('PRAGMA foreign_keys=ON')
            connection.executescript(SCHEMA)
            os.chmod(db, 0o600)
            cursor = connection.execute(
                'INSERT OR IGNORE INTO snapshots(kind,region_code,period,sha256,format,row_count) VALUES(?,?,?,?,?,?)',
                (kind, region_code, period, digest, fmt, len(rows) if rows is not None else None))
            snapshot_id = connection.execute(
                'SELECT id FROM snapshots WHERE kind=? AND region_code=? AND period=? AND sha256=?',
                (kind, region_code, period, digest)).fetchone()[0]
            if cursor.rowcount and rows is not None:
                connection.executemany('INSERT INTO records VALUES(?,?,?,?)',
                    ((snapshot_id, i, row[0], json.dumps(row, ensure_ascii=False, separators=(',', ':'), allow_nan=False))
                     for i, row in enumerate(rows)))
            connection.execute('INSERT OR IGNORE INTO observations(snapshot_id,observed_at,origin,observation_key,source_modified_at) VALUES(?,?,?,?,?)',
                               (snapshot_id, observed, origin, key, modified))
            connection.commit()
        return digest


def save_rows(root, source, kind, code, month, rows, **kwargs):
    width = 9 if source == 'trades' else 11 if source == 'rents' else None
    if width is None or kind not in (('apt', 'rh', 'offi') if source == 'trades' else ('apt',)) or not re.fullmatch(r'\d{5}', str(code)) or not re.fullmatch(r'\d{4}(0[1-9]|1[0-2])', str(month)):
        raise ValueError('Invalid transaction scope')
    if not isinstance(rows, list):
        raise ValueError('Invalid transaction rows')
    for row in rows:
        if not isinstance(row, list) or len(row) != width or not isinstance(row[0], str):
            raise ValueError('Invalid transaction row')
        date = dt.date.fromisoformat(row[0])
        if date.strftime('%Y%m') != month:
            raise ValueError('Contract date outside requested month')
        if any(not isinstance(v, (str, int, float, type(None))) for v in row):
            raise ValueError('Invalid transaction field')
    body = json.dumps(rows, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    return record(root, source, kind, code, month, body, 'json', rows=rows, **kwargs)


def save_file(root, source, kind, period, path, origin='download'):
    path = Path(path)
    stat = path.stat()
    return record(root, source, kind, '', period, path.read_bytes(), path.suffix.lstrip('.'), origin=origin,
                  observation_key=str(stat.st_mtime_ns) if origin == 'cache_import' else None,
                  modified=dt.datetime.fromtimestamp(stat.st_mtime, dt.timezone.utc).isoformat() if origin == 'cache_import' else None)


def save_cached_rows(root, source, kind, code, month, rows, path):
    stat = Path(path).stat()
    return save_rows(root, source, kind, code, month, rows, origin='cache_import',
                     observation_key=str(stat.st_mtime_ns),
                     modified=dt.datetime.fromtimestamp(stat.st_mtime, dt.timezone.utc).isoformat())


def import_cache(root, cache_root):
    total = 0
    cache_root = Path(cache_root)
    for source, paths in [('trades', sorted((cache_root / 'molit').glob('*/*.json'))),
                          ('rents', sorted((cache_root / 'molit-rents').glob('*.json')))]:
        for path in paths:
            match = re.fullmatch(r'(\d{5})_(\d{6})\.json', path.name)
            if not match:
                continue
            stat = path.stat()
            rows = json.loads(path.read_text(encoding='utf-8'))
            save_rows(root, source, path.parent.name if source == 'trades' else 'apt',
                      match[1], match[2], rows, origin='cache_import',
                      observation_key=str(stat.st_mtime_ns),
                      modified=dt.datetime.fromtimestamp(stat.st_mtime, dt.timezone.utc).isoformat())
            total += 1
            if total % 1000 == 0:
                print(f'Imported {total} monthly files', flush=True)
    for source, pattern in [('supply', '*.xlsx'), ('pipeline', '*.xls'), ('moveins', '*.csv')]:
        for path in sorted((cache_root / source).glob(pattern)):
            if source == 'pipeline':
                kind, period = path.stem.split('_', 1)
            elif source == 'supply':
                kind, period = 'unsold', path.stem[:4] + '-' + path.stem[4:]
            else:
                kind, period = 'scheduled', 'previous-asof-unknown'
            save_file(root, source, kind, period, path, origin='cache_import')
            total += 1
    extra = cache_root / 'extra.json'
    if extra.exists():
        from market_extra import valid_feed
        data = json.loads(extra.read_text(encoding='utf-8'))
        stat = extra.stat()
        for kind in ('apt_trades', 'unsold', 'rates'):
            feed = data.get(kind)
            if valid_feed(feed):
                document = {k: feed[k] for k in ('months', 'values', 'source') if k in feed}
                document['collected'] = feed.get('collected', data.get('collected'))
                record(root, 'extra', kind, '', feed['months'][-1],
                       json.dumps(document, ensure_ascii=False, allow_nan=False).encode('utf-8'),
                       'json', origin='cache_import', observation_key=str(stat.st_mtime_ns),
                       modified=dt.datetime.fromtimestamp(stat.st_mtime, dt.timezone.utc).isoformat())
                total += 1
    return total


def inventory(root):
    result = {}
    for source in SOURCES:
        db = Path(root) / 'storage' / source / 'archive.sqlite3'
        if db.exists():
            with closing(sqlite3.connect('file:' + str(db.resolve()) + '?mode=ro', uri=True)) as connection:
                result[source] = {table: connection.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                                  for table in ('snapshots', 'records', 'observations')}
                result[source]['periods'] = connection.execute('SELECT MIN(period),MAX(period) FROM snapshots').fetchone()
    return result


def backup(root, dest):
    """Consistent per-source SQLite backup plus all files referenced by that backup."""
    dest = Path(dest)
    for source in SOURCES:
        base = Path(root) / 'storage' / source
        db = base / 'archive.sqlite3'
        if not db.exists():
            continue
        target = dest / source
        if target.exists():
            raise ValueError('Backup destination already exists')
        target.mkdir(parents=True, mode=0o700)
        with closing(sqlite3.connect('file:' + str(db.resolve()) + '?mode=ro', uri=True)) as connection:
            with closing(sqlite3.connect(target / 'archive.sqlite3')) as output:
                connection.backup(output)
                hashes = [r[0] for r in output.execute('SELECT DISTINCT sha256 FROM snapshots')]
        os.chmod(target / 'archive.sqlite3', 0o600)
        (target / 'blobs').mkdir(mode=0o700)
        for digest in hashes:
            payload = (base / 'blobs' / (digest + '.gz')).read_bytes()
            if hashlib.sha256(gzip.decompress(payload)).hexdigest() != digest:
                raise ValueError('Backup checksum mismatch')
            out = target / 'blobs' / (digest + '.gz')
            out.write_bytes(payload)
            os.chmod(out, 0o600)
        (target / 'manifest.json').write_text(json.dumps({'schema_version': 1, 'created_at': now(), 'sha256': hashes}), encoding='utf-8')


def verify(path):
    checked = 0
    for source in SOURCES:
        base = Path(path) / source
        db = base / 'archive.sqlite3'
        if not db.exists():
            continue
        with closing(sqlite3.connect('file:' + str(db.resolve()) + '?mode=ro', uri=True)) as connection:
            if connection.execute('PRAGMA quick_check').fetchone()[0] != 'ok' or connection.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('Archive database integrity failure')
            if connection.execute('SELECT s.id FROM snapshots s LEFT JOIN records r ON s.id=r.snapshot_id WHERE s.row_count IS NOT NULL GROUP BY s.id HAVING COUNT(r.ordinal)!=s.row_count').fetchone():
                raise ValueError('Archive record count mismatch')
            for digest, in connection.execute('SELECT DISTINCT sha256 FROM snapshots'):
                payload = gzip.decompress((base / 'blobs' / (digest + '.gz')).read_bytes())
                if hashlib.sha256(payload).hexdigest() != digest:
                    raise ValueError('Archive checksum mismatch')
                checked += 1
    return checked


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    ingest = sub.add_parser('import-cache')
    ingest.add_argument('--cache-root', type=Path, default=ROOT / 'cache')
    sub.add_parser('status')
    check = sub.add_parser('verify')
    check.add_argument('--path', type=Path, default=ROOT / 'storage')
    copy = sub.add_parser('backup')
    copy.add_argument('--dest', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'import-cache':
        print('Imported cache files:', import_cache(ROOT, args.cache_root))
    elif args.action == 'backup':
        backup(ROOT, args.dest)
        verify(args.dest)
        print('Archive backup completed')
    elif args.action == 'verify':
        print('Verified archive blobs:', verify(args.path))
    else:
        print(json.dumps(inventory(ROOT), ensure_ascii=False, indent=2))
