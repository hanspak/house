# Codex 인수인계

- 초기 설정일: 2026-10-08 (KST)
- 이번 작업: Claude/Codex 독립 worktree, 공통 개발 지침 및 역할별 작업 기록 구성.
- 이전 완료: 전국·17개 시도 실거래 선택 기능과 수집/배포 분리. 관련 커밋 `8c535a9`, `387a17f`.
- 이번 변경: AGENTS.md, Claude 공통 지침, 개발·동시 작업 문서, worktree 준비 스크립트.
- 검증 완료: 두 worktree의 브랜치·소스·캐시 분리, 준비 스크립트 재실행, 인증 파일 Git 제외·0600 권한을 확인했다. Codex에서 단위 검사 10개 통과, 양쪽 폴더에서 `--snapshot` 화면 생성 성공. 각 Git 작업 폴더는 깨끗하다.
- 환경 기준 커밋: `1be4c69`. 검증 기록은 이 파일의 Git 이력에서 확인한다.
- 남은 작업: Codex IDE를 `.worktrees/codex/codex.code-workspace`로 열고 새 세션에서 작업한다. Claude 세션도 자신의 IDE 창으로 이동한다.
- 원격 반영: 이번 환경 설정은 로컬 구성이다. GitHub push와 사이트 배포는 별도다.
