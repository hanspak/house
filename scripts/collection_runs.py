"""Record collection outcomes without command arguments, URLs or error bodies."""
import argparse
import datetime as dt
import json
from pathlib import Path
import signal
import subprocess

ROOT = Path(__file__).resolve().parents[1]
NAMES = ('trades', 'apt_trades', 'buyer_residence', 'buyer_age', 'unsold', 'rates', 'rents', 'supply', 'pipeline', 'moveins')


def stamp():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(timespec='seconds')


def read(path):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if data.get('schema_version') == 1 else {}
    except (OSError, ValueError, AttributeError):
        return {}


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix('.part')
    part.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    part.replace(path)


def execute(root, name, command, timeout, result=None):
    path = root / 'cache/published/collection-status' / (name + '.json')
    data = read(path)
    event = {'started': stamp(), 'status': 'running'}
    data.update(schema_version=1, name=name, last_attempt=event)
    write(path, data)
    status, reason, code = 'failure', '', 1
    try:
        completed = subprocess.run(command, cwd=root, timeout=timeout, check=False)
        code = completed.returncode
        if code:
            reason = 'process_exit'
        elif result:
            payload = json.loads((root / result).read_text(encoding='utf-8'))
            failures = payload.get('failed', 0)
            if failures:
                status, reason, code = 'partial', 'incomplete_collection', 1
                event['failed_requests'] = failures
            else:
                status = 'success'
        else:
            status = 'success'
    except subprocess.TimeoutExpired:
        status, reason = 'timeout', 'time_limit'
    except KeyboardInterrupt:
        status, reason = 'interrupted', 'execution_interrupted'
    except (OSError, ValueError, TypeError, AttributeError):
        reason = 'execution_or_result_error'
    event.update(finished=stamp(), status=status, reason=reason)
    data['last_attempt'] = event
    data['events'] = (data.get('events', []) + [dict(event)])[-30:]
    if status == 'success':
        data['last_success'] = event['finished']
    write(path, data)
    print(f'Collection {name}: {status}', flush=True)
    return code if code else (0 if status == 'success' else 1)


def summary(root):
    return [{**read(root / 'cache/published/collection-status' / (name + '.json')),
             'name': name} for name in NAMES]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', choices=NAMES, required=True)
    parser.add_argument('--timeout', type=int, required=True)
    parser.add_argument('--result')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command or args.timeout < 1:
        parser.error('A command and positive timeout are required')
    def interrupted(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    raise SystemExit(execute(ROOT, args.name, command, args.timeout, args.result))
