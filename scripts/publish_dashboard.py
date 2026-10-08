"""커밋된 작업을 검사하고 main에 통합·push한 뒤 실제 Pages 게시를 확인한다."""
import argparse
import fcntl
import json
import hashlib
import re
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
        run(root, 'node', '--test', 'tests/market_analysis.test.cjs', 'tests/overview_comparison.test.cjs')
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
                        kb_pages = [page.replace('trades.html', name) for name in ('index.html', 'monthly.html')]
                        analysis = (root / 'scripts/market_analysis.js').read_text(encoding='utf-8')
                        kb_html = [get(url + '?v=' + sha) for url in kb_pages]
                        if any(f'name="build-commit" content="{sha}"' not in html or analysis not in html for html in kb_html):
                            time.sleep(20)
                            continue
                        print('주간·월간 화면 커밋 및 계산 모듈 게시 확인', flush=True)
                        if (root / 'scripts/market_overview.py').exists():
                            overview = page.replace('trades.html', 'overview.html')
                            page_html = get(overview + '?v=' + sha)
                            if f'name="build-commit" content="{sha}"' not in page_html:
                                time.sleep(20)
                                continue
                            comparison = (root / 'scripts/overview_comparison.js').read_text(encoding='utf-8')
                            if comparison not in page_html:
                                raise SystemExit('공개 종합 화면의 비교 계산 모듈이 예상과 다릅니다.')
                            match = re.search(r'"revision_file":"(overview-data/revisions\.([a-f0-9]{12})\.json)"', page_html)
                            if not match and (root / 'scripts/data_revisions.py').exists():
                                raise SystemExit('공개 종합 화면에 변경 이력 파일 연결이 없습니다.')
                            if match:
                                body = get(overview.rsplit('/', 1)[0] + '/' + match[1])
                                if hashlib.sha256(body.encode()).hexdigest()[:12] != match[2] or json.loads(body).get('schema_version') != 1:
                                    raise SystemExit('변경 이력 파일의 공개 내용이 예상과 다릅니다.')
                                print('변경 이력 파일 게시 확인', flush=True)
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
