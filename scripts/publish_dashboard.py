"""커밋된 작업을 검사하고 main에 통합·push한 뒤 실제 Pages 게시를 확인한다."""
import argparse
import fcntl
import http.client
import json
import hashlib
import re
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request
import urllib.parse


def run(root, *args, capture=False):
    result = subprocess.run(args, cwd=root, check=True, text=True,
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else None


def git(root, *args):
    return run(root, 'git', *args, capture=True)


def get(url, deadline=None):
    req = urllib.request.Request(url, headers={'User-Agent': 'house-publish-check', 'Cache-Control': 'no-cache'})
    host = urllib.parse.urlsplit(url).hostname or ''
    for attempt in range(4):
        remaining = deadline - time.monotonic() if deadline is not None else float('inf')
        if remaining <= 0:
            raise TimeoutError('Publication verification deadline exceeded')
        delay = 2 ** (attempt + 1)
        try:
            with urllib.request.urlopen(req, timeout=min(40, remaining)) as response:
                return response.read().decode('utf-8')
        except urllib.error.HTTPError as error:
            retryable = error.code in (408, 429, 500, 502, 503, 504) or (error.code == 404 and host.endswith('.github.io'))
            hint = error.headers.get('Retry-After') if error.headers else None
            if hint and hint.isdigit():
                delay = min(15, int(hint))
            reason = 'HTTP ' + str(error.code)
            error.close()
            if not retryable or attempt == 3:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.IncompleteRead) as error:
            reason = type(error).__name__
            if attempt == 3:
                raise
        if deadline is not None and time.monotonic() + delay >= deadline:
            raise TimeoutError('Publication verification deadline exceeded')
        print(f'공개 확인 재시도 {attempt + 2}/4 · {host} · {reason} · {delay}초 후', flush=True)
        time.sleep(delay)


def verify_public(root, repo, sha, deadline):
    base = f'https://{repo.split("/")[0]}.github.io/{repo.split("/")[1]}/'
    modules = {'trades.html': 'profile_loader.js', 'index.html': 'market_analysis.js',
               'monthly.html': 'market_analysis.js', 'overview.html': 'overview_comparison.js'}
    pages = {}
    for name, module in modules.items():
        html = get(base + name + '?v=' + sha, deadline=deadline)
        if f'name="build-commit" content="{sha}"' not in html:
            return False
        if (root / 'scripts' / module).read_text(encoding='utf-8') not in html:
            raise SystemExit(f'공개 {name}의 계산 모듈이 예상과 다릅니다.')
        pages[name] = html
    match = re.search(r'"revision_file":"(overview-data/revisions\.([a-f0-9]{12})\.json)"', pages['overview.html'])
    if not match:
        raise SystemExit('공개 종합 화면에 변경 이력 파일 연결이 없습니다.')
    body = get(base + match[1], deadline=deadline)
    if hashlib.sha256(body.encode()).hexdigest()[:12] != match[2] or json.loads(body).get('schema_version') != 1:
        raise SystemExit('변경 이력 파일의 공개 내용이 예상과 다릅니다.')
    print('공개 4개 화면 커밋·계산 모듈 및 변경 이력 해시 확인 완료', flush=True)
    print(f'게시 확인: {base}trades.html\n커밋: {sha}', flush=True)
    return True


def rate_limited(error):
    return error.code == 429 or (error.code == 403 and (error.headers or {}).get('X-RateLimit-Remaining') == '0')


def publish(root, timeout=600):
    common = Path(git(root, 'rev-parse', '--git-common-dir'))
    common = common if common.is_absolute() else root / common
    common = common.resolve()
    integration = common.parent
    # 협업 도구가 이 명령을 함께 사용해도 main 통합은 한 번에 한 작업만 수행한다.
    with (common / 'house-publish.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for folder in {root, integration}:
            if git(folder, 'status', '--porcelain'):
                raise SystemExit(f'{folder}: 미커밋 변경이 있습니다. 담당 변경을 먼저 커밋하세요.')
        if git(integration, 'branch', '--show-current') != 'main':
            raise SystemExit('통합 폴더가 main이 아닙니다. 브랜치를 자동 변경하지 않습니다.')
        run(root, 'node', '--test', 'tests/market_analysis.test.cjs', 'tests/overview_comparison.test.cjs', 'tests/profile_loader.test.cjs')
        run(root, 'python3', '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-v')
        run(root, 'python3', '-B', 'scripts/kb_trades_dashboard.py', '--snapshot')
        if (root / 'scripts/market_overview.py').exists():
            run(root, 'python3', '-B', 'scripts/kb_dashboard.py')
            run(root, 'python3', '-B', 'scripts/kb_monthly_dashboard.py')
            run(root, 'python3', '-B', 'scripts/market_overview.py')
        run(root, 'git', 'diff', '--check')
        sha = git(root, 'rev-parse', 'HEAD')
        run(integration, 'git', 'fetch', 'origin', 'main')
        # 원격 변경 또는 다른 작업이 있으면 안전한 fast-forward가 가능한 경우만 통합한다.
        run(root, 'git', 'merge-base', '--is-ancestor', 'origin/main', sha)
        run(integration, 'git', 'merge', '--ff-only', sha)
        run(integration, 'git', 'push', 'origin', 'main')
        repo = git(root, 'remote', 'get-url', 'origin').removesuffix('.git').split('github.com')[-1].lstrip('/:')
        api = f'https://api.github.com/repos/{repo}/actions/runs?head_sha={sha}&per_page=5'
        end = time.monotonic() + timeout
        def read(url):
            return get(url, deadline=end)
        last_state = None
        api_limited = False
        while time.monotonic() < end:
            if api_limited:
                if verify_public(root, repo, sha, end):
                    print('Actions status unavailable; publication verified from public files.', flush=True)
                    return
                time.sleep(20)
                continue
            try:
                runs = json.loads(read(api))['workflow_runs']
                workflow = next((r for r in runs if r['path'].startswith('.github/workflows/dashboard.yml')), None)
                jobs = json.loads(read(workflow['jobs_url']))['jobs'] if workflow else []
            except urllib.error.HTTPError as error:
                if not rate_limited(error):
                    raise
                error.close()
                api_limited = True
                print('GitHub API rate limit: verifying public files; Actions status unavailable.', flush=True)
                continue
            if workflow:
                states = [(j['name'], j['status'], j['conclusion']) for j in jobs]
                if states != last_state:
                    print('Actions:', states, flush=True)
                    last_state = states
                deploy = next((j for j in jobs if j['name'] == 'deploy'), None)
                if deploy and deploy['conclusion'] == 'success' and verify_public(root, repo, sha, end):
                    print('Actions:', workflow['html_url'], flush=True)
                    if any(j['name'] == 'freshness' and j['conclusion'] == 'failure' for j in jobs):
                        print('Publication succeeded; source freshness warning remains.', flush=True)
                    return
                if workflow['status'] == 'completed' and (not deploy or deploy['conclusion'] != 'success'):
                    raise SystemExit('Deployment failed: ' + workflow['html_url'])
            time.sleep(20)
        raise SystemExit('Publication verification deadline exceeded. Check Actions and public pages.')



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeout', type=int, default=600)
    args = parser.parse_args()
    try:
        publish(Path(__file__).resolve().parents[1], args.timeout)
    except (subprocess.CalledProcessError, urllib.error.URLError, BlockingIOError, TimeoutError, ConnectionError, http.client.IncompleteRead) as error:
        reason = 'HTTP ' + str(error.code) if isinstance(error, urllib.error.HTTPError) else type(error).__name__
        raise SystemExit(f'자동 배포 중단: {reason}. 로그의 Git/배포 상태를 확인하세요.')
