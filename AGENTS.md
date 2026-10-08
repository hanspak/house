# Codex 작업 지침

- 공통 개발 규칙은 `docs/project-guide.md`, 동시 작업 절차는 `docs/parallel-work.md`를 따른다.
- 매물 검색·등록·출처·가격 단위 규칙은 `CLAUDE.md`의 기존 매물 관리 규칙을 공통으로 적용한다.
- 수정 전에 `git status --short`와 `git branch --show-current`를 확인한다. Codex의 기본 작업 위치는 `.worktrees/codex`, 브랜치는 `work/codex`다. 통합 폴더에서 시작했다면 자신의 worktree로 이동해 작업한다.
- Claude 폴더와 다른 작업자의 미커밋 변경을 수정·되돌리거나 대신 커밋하지 않는다. 사용자 지시로 통합하는 경우에만 통합 폴더를 사용한다.
- 작업을 이어받을 때 자신의 `docs/handoff/codex.md`를 확인한다. 다른 도구의 결과를 통합할 때 해당 커밋과 인수인계 파일을 확인한다.
- 주요 작업 종료 시 자신의 인수인계 파일에 목표, 변경, 검증, 커밋, 남은 작업을 기록한다. 공통 규칙 변경은 관련 문서에 반영한다.
- 테스트·생성 명령은 자신의 worktree에서 실행한다. 화면은 `scripts/*_template.html`과 생성기를 수정한다.
- 로컬 커밋, main 통합, 원격 push, Pages 배포를 구분해 보고한다. 검토한 담당 변경만 통합한다.
- 인증 키·서비스 계정 JSON·API 응답 원본은 커밋하거나 출력하지 않는다.
