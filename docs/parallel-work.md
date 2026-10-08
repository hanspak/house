# Claude와 Codex 동시 작업

## 작업 위치

| 용도 | 폴더 (프로젝트 루트 기준) | 브랜치 |
|---|---|---|
| 결과 통합 | `.` | `main` |
| Claude 개발 | `.worktrees/claude` | `work/claude` |
| Codex 개발 | `.worktrees/codex` | `work/codex` |

각 worktree는 Git 이력과 저장소 설정을 공유하지만 소스 파일, 인덱스, 생성물, 캐시는 별도다. 통합 폴더에서 두 도구가 동시에 수정하지 않는다. 같은 소스를 서로 다른 worktree에서 수정할 수 있지만 통합 시 충돌을 해결해야 할 수 있다.

## IDE와 기존 세션

Claude는 `.worktrees/claude/claude.code-workspace`, Codex는 `.worktrees/codex/codex.code-workspace`를 **각각 별도 IDE 창**으로 열고 해당 도구의 새 세션을 시작한다. 기존 세션의 작업 폴더는 자동 변경되지 않는다. 기존 세션에 진행 상황을 자신의 인수인계 파일에 남기고 새 창으로 이동하도록 요청한다.

터미널에서는 프로젝트 루트 기준으로 `cd .worktrees/claude` 후 `claude`, 또는 `cd .worktrees/codex` 후 `codex`를 실행한다.

## 준비 및 복구

통합 폴더에서 `python3 scripts/setup_parallel_work.py`를 실행한다. 존재하는 작업 폴더는 브랜치를 확인하고 재사용하며, 변경 파일을 초기화하지 않는다. IDE 파일은 Git에서 제외되는 각 worktree에 생성한다.

초기 준비 시 루트의 `kbdata/*.xlsx`, `cache/trades.json`, `cache/extra.json`, `cache/published/`와 `secrets/`의 일반 파일을 각 worktree에 독립 복사한다. 기존 대상 파일은 덮어쓰지 않는다. 원본 월별 `cache/molit/`는 복사하지 않는다. 인증 정보는 로컬에만 남고 권한은 0600으로 설정한다. 복사를 생략하려면 `--skip-local-data`를 사용한다. 가상 환경이 필요하면 각 작업 폴더에 생성한다.

Git worktree는 보안 격리가 아니다. 같은 사용자의 다른 폴더에 접근할 수 있으므로 상대 폴더를 수정하지 않는 지침을 함께 따른다. 동시 대규모 API 수집은 요청 제한을 공유하므로 한 도구에만 맡긴다.

## 기록과 통합

1. 시작 시 자신의 브랜치와 Git 상태, 인수인계 파일을 확인하고 담당 작업·파일 범위를 기록한다.
2. Claude는 `docs/handoff/claude.md`, Codex는 `docs/handoff/codex.md`에 기록한다. 다른 브랜치의 미커밋 기록은 자동 공유되지 않는다. 기록을 커밋하면 다른 worktree에서 `git show work/claude:docs/handoff/claude.md` 같은 명령으로 확인할 수 있다.
3. 완료 시 담당 파일을 명시적으로 스테이징하고 자신의 브랜치에서 커밋한다. 인수인계에는 검증과 남은 작업을 기록한다. 통합 폴더에서 다른 작업까지 포함할 수 있는 `git add -A`를 사용하지 않는다.
4. 통합 담당자는 main 폴더가 깨끗한지 확인한 뒤 검토한 커밋만 `git cherry-pick <커밋SHA>`로 가져온다. 충돌 시 양쪽 의도를 확인하고 필요한 검사를 다시 실행한다.
5. 원격 반영 요청을 받은 통합 담당자 한 명이 최신 origin/main을 확인한 후 main을 push하고 배포 결과를 확인한다. 두 도구가 동시에 main을 통합하거나 push하지 않는다.
6. 다음 작업 전 자신의 worktree가 깨끗할 때 `git merge main`으로 통합 결과를 반영한다. 미커밋 작업은 먼저 보존한다. 강제 초기화하지 않는다.

공통 규칙 변경은 관련 문서에, 일회성 진행 상황은 역할별 인수인계에 기록한다. 상세 변경은 Git 커밋 이력으로 확인한다.
