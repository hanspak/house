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


## 조건별 실거래 분석

실거래 계산은 `scripts/trade_analysis.py`에 모으고 HTML은 계산 결과 표시와 조건 선택을 담당한다. 공개 집계 규격은 `analysis_version`으로 구분한다. 규격 변경 시 게시용 `data/trades.json.gz`도 같은 규격으로 생성해야 한다.

`--snapshot`은 HTML과 `dashboard/trades-data/` 조건별 JSON을 함께 생성한다. 배포할 때 둘 다 포함한다. 조건 필터 미리보기는 파일을 직접 여는 대신 자신의 worktree에서 아래 명령을 실행하고 http://localhost:8765/trades.html 을 연다. 두 도구가 동시에 실행할 때는 포트를 다르게 지정한다.

```sh
python3 -m http.server 8765 --directory dashboard
```

원자료 수정 이력과 다른 화면의 계산 분리는 후속 작업이다.

## 관심 지역 종합

`overview.html`은 전국·17개 시도·시군구의 가격, 거래 회복률, 임대차, 준공 후 미분양, 구매 부담을 함께 표시한다. 관심 지역 최대 6곳을 브라우저에 저장하고 비교·링크 공유·CSV 내려받기를 제공한다.

주간·월간·실거래 생성기는 `scripts/overview_data.py`를 통해 `dashboard/overview-input/`에 표시용 자료를 저장한다. `scripts/market_overview.py`가 이를 공통 지표 형식(값·단위·기간·권역·설명)으로 통합하고 `overview_template.html`에 넣는다. 입력 JSON은 Pages에 게시하지 않는다. 시군구 KB 자료가 없으면 상위 지역 자료임을 표시한다.

- `scripts/housing_supply.py`: 국토부 공식 엑셀의 전체·준공 후 미분양을 최근 6개월 추출한다.
- `scripts/molit_rents.py`: 전국 아파트 전월세 최근 6개월을 월별 캐시에 저장하고 집계한다. 기존 매매용 키로 아파트 전월세 API 이용 권한도 필요하다.
- `data/supply.json.gz`, `data/rents.json.gz`: 처음 게시할 때 쓰는 공개 집계. 인증키·아파트명·개별 계약을 넣지 않는다.
- `cache/published/housing/`: 마지막 완전한 공급·전월세 집계. 예약 수집 후 다음 배포가 읽는다. 불완전한 전월세 수집은 게시 자료를 덮어쓰지 않는다.

```sh
python3 scripts/kb_dashboard.py
python3 scripts/kb_monthly_dashboard.py
python3 scripts/kb_trades_dashboard.py --snapshot
python3 scripts/market_overview.py
```

사용자가 검증 후 자동 배포를 허용했다. 자신의 담당 변경을 커밋한 후 `python3 scripts/publish_dashboard.py`를 실행한다. 검사 → main fast-forward 통합 → push → Pages 및 공개 페이지의 커밋 일치 확인 순서다. 공통 Git 잠금으로 동시 배포를 막으며 미커밋 변경·분기 충돌 시 덮어쓰지 않고 중단한다.
