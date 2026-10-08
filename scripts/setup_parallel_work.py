"""Claude/Codex worktree를 만들고 로컬 입력 자료를 독립 복사한다."""
import argparse
import json
import shutil
import subprocess
from pathlib import Path


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


def copy_new(source, target, private=False):
    if not source.is_file() or source.is_symlink() or target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as dest:
        if private:
            target.chmod(0o600)
        with source.open('rb') as src:
            shutil.copyfileobj(src, dest)


def setup(root, skip_local_data=False):
    common = Path(git(root, 'rev-parse', '--git-common-dir'))
    if not common.is_absolute():
        common = root / common
    root = common.resolve().parent
    for role in ('claude', 'codex'):
        target = root / '.worktrees' / role
        branch = f'work/{role}'
        if target.exists():
            actual = git(target, 'branch', '--show-current')
            if actual != branch:
                raise SystemExit(f'{target}: 예상 브랜치 {branch}, 실제 {actual}. 자동 변경하지 않습니다.')
        else:
            exists = subprocess.run(['git', '-C', str(root), 'show-ref', '--verify', '--quiet', f'refs/heads/{branch}']).returncode == 0
            args = ['worktree', 'add', str(target), branch] if exists else ['worktree', 'add', '-b', branch, str(target), 'main']
            subprocess.run(['git', '-C', str(root), *args], check=True)
        if not skip_local_data:
            files = list((root / 'kbdata').glob('*.xlsx'))
            files += [root / 'cache' / name for name in ('trades.json', 'extra.json')]
            files += list((root / 'cache' / 'published').glob('*.gz'))
            files += [p for p in (root / 'secrets').glob('*') if p.is_file()]
            for source in files:
                copy_new(source, target / source.relative_to(root), private=source.parent.name == 'secrets')
        workspace = target / f'{role}.code-workspace'
        if not workspace.exists():
            workspace.write_text(json.dumps({'folders': [{'name': f'house — {role}', 'path': '.'}]}, ensure_ascii=False, indent=2) + '\n')
        subprocess.run(['git', '-C', str(target), 'check-ignore', '--quiet', workspace.name], check=True)
        print(f'{role}: {target} [{branch}]')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-local-data', action='store_true')
    args = parser.parse_args()
    setup(Path(__file__).resolve().parent.parent, args.skip_local_data)
