# 공통 프로젝트 개발 규칙

Claude와 Codex가 함께 참조하는 문서다. 매물 검색·등록 규칙과 기존 프로젝트 구조는 루트 `CLAUDE.md`에 유지한다. 동시 개발 절차는 `parallel-work.md`에 있다.

## 소스와 데이터

- Python 생성기와 HTML 템플릿은 `scripts/`, 검증 코드는 `tests/`에 있다.
- `dashboard/`는 생성물이다. 화면 변경은 해당 `scripts/*_template.html`에 반영하고 생성기를 실행한다.
- `kbdata/` 원본 엑셀, `cache/` API 캐시, `secrets/` 인증 정보는 Git에서 제외한다.
- `data/trades.json.gz`는 게시용 전국 집계 자료다. API 키나 원본 API 응답을 넣지 않는다.
- 날짜·가격·면적·매물 저장 기준은 `CLAUDE.md`의 매물 관리 규칙을 따른다.
- 수집 누락 지역·월은 거래 0건으로 간주하지 않는다. 전국 중위가격은 실제 거래를 합쳐 계산한다.

## 확인 명령

```sh
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -v
python3 scripts/kb_trades_dashboard.py --snapshot
git diff --check
```

집계·수집 로직 변경 시 단위 검사를 실행한다. 화면 변경 시 생성된 HTML을 브라우저에서 확인한다. `--snapshot`은 API 호출 없이 마지막 완전한 전국 집계 자료로 화면을 생성한다.

## 배포

GitHub Pages: https://hanspak.github.io/house/trades.html

`.github/workflows/dashboard.yml`은 main의 관련 변경을 게시한다. 실거래 화면은 집계 자료로 먼저 게시하고, 정기·수동 실행의 데이터 갱신은 배포 뒤 별도 작업으로 수행한다. 수집 실패가 화면 게시를 막는 구조로 되돌리지 않는다. 상세 설정은 `google-drive-setup.md`를 참고한다.

커밋, 원격 push, Actions 실행, Pages 게시를 각각 확인한다. 공개 주소 확인 전에는 배포 완료라고 보고하지 않는다. 자료 기준일은 실제 수집일을 유지한다.
