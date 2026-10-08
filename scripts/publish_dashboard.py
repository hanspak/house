"""커밋된 작업을 검사하고 main에 통합·push한 뒤 실제 Pages 게시를 확인한다."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request


def run(root, *args, capture=False):
    result = subprocess.run(args, cwd=root, check=True, text=True,
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else None


def git(root, *args):
    return run(root, 'git', *args, capture=True)


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'house-publish-check', 'Cache-Control': 'no-cache'})
    with urllib.request.urlopen(req, timeout=40) as response:
        return response.read().decode('utf-8')


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
        last_state = None
        while time.monotonic() < end:
            runs = json.loads(get(api))['workflow_runs']
            workflow = next((r for r in runs if r['path'].startswith('.github/workflows/dashboard.yml')), None)
            if workflow:
                jobs = json.loads(get(workflow['jobs_url']))['jobs']
                states = [(j['name'], j['status'], j['conclusion']) for j in jobs]
                if states != last_state:
                    print('배포 진행:', states, flush=True)
                    last_state = states
                deploy = next((j for j in jobs if j['name'] == 'deploy'), None)
                if deploy and deploy['conclusion'] == 'success':
                    page = f'https://{repo.split("/")[0]}.github.io/{repo.split("/")[1]}/trades.html'
                    if f'name="build-commit" content="{sha}"' in get(page + '?v=' + sha):
                        if (root / 'scripts/market_overview.py').exists():
                            overview = page.replace('trades.html', 'overview.html')
                            if f'name="build-commit" content="{sha}"' not in get(overview + '?v=' + sha):
                                time.sleep(20)
                                continue
                            print(f'종합 화면 게시 확인: {overview}', flush=True)
                        print(f'게시 확인: {page}\n커밋: {sha}\nActions: {workflow["html_url"]}', flush=True)
                        if any(j['name'] == 'freshness' and j['conclusion'] == 'failure' for j in jobs):
                            print('자료 기준일 점검 알림이 있습니다. 배포는 성공했습니다.', flush=True)
                        return
                if workflow['status'] == 'completed' and (not deploy or deploy['conclusion'] != 'success'):
                    raise SystemExit(f'배포 실패: {workflow["html_url"]}')
            time.sleep(20)
        raise SystemExit('배포 확인 제한 시간을 초과했습니다. Actions 및 공개 주소를 확인하세요.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeout', type=int, default=600)
    args = parser.parse_args()
    try:
        publish(Path(__file__).resolve().parents[1], args.timeout)
    except (subprocess.CalledProcessError, urllib.error.URLError, BlockingIOError) as error:
        raise SystemExit(f'자동 배포 중단: {type(error).__name__}. 로그의 Git/배포 상태를 확인하세요.')
