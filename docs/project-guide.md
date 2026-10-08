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

공개 집계 수정 이력은 `data_revisions.py`, 주간·월간 공통 계산은 `market_analysis.js`에서 관리한다.

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

## 공개 집계 변경 기록

`data_revisions.py`는 공급·전월세·실거래의 마지막 완전한 집계와 새 집계를 같은 지역·월·지표로 비교한다. `save_published()`가 이력 메타데이터를 집계에 포함하고 원자적으로 저장한다. 불완전한 건수 및 더 오래된 수집 자료로 게시 집계를 덮어쓰지 않는다. 가격 표본 표시 정책이 달라지거나 분석 규격이 바뀌면 이전 규격과 비교하지 않는다.

수집 캐시와 기본 `data/*.json.gz` 중 최신 호환 집계가 기준이다. 내용이 바뀌지 않은 재생성은 변경 이벤트를 만들지 않는다. 원거래·키는 이력에 포함하지 않는다. 현재 기본 파일은 이력 추적의 시작 기준만 등록했고 실제 변경은 후속 수집부터 누적한다.

종합 생성기는 `dashboard/overview-data/revisions.<내용해시>.json`을 함께 만든다. Pages artifact에 `overview-data/`도 포함해야 한다. 자동 배포 명령은 공개 HTML뿐 아니라 이력 JSON의 해시 일치까지 확인한다. 이력은 자료별 최근 변경 수집 12회·변경 값 20,000개 한도이며 영구 원자료 감사 저장소가 아니다.

## 공급 실적·입주예정 연결

- `housing_pipeline.py`: 인증키 없이 국토부 공식 인허가·착공·준공 최근 6개월 XLS를 다시 읽는다. `xlrd`로 아파트 월계·기준월·전국 합계를 점검한다. 공표 권역 변경은 원래 권역으로 유지한다.
- `housing_moveins.py`: 공공데이터포털 공식 다운로드 조회로 최신 CSV를 받아 항목·전체 행 수·전망 범위를 점검한다. 예정월 미정과 주소 연결 실패를 별도로 보존한다. 포털 메타데이터 `contentUrl`은 다른 첨부를 가리킬 수 있어 실제 다운로드 버튼의 조회 경로를 사용한다.
- 공개 기본 자료: `data/pipeline.json.gz`, `data/moveins.json.gz`. 공급 단계·지역·월 집계만 담고 개별 단지명·주소는 공개 집계에 넣지 않는다. 원본은 로컬 `cache/pipeline/`, `cache/moveins/`에 둔다.
- `housing` Actions에 두 수집기를 추가했다. 기존 캐시 복원 경로를 유지해 전월세 월별 캐시와 변경 이력을 잃지 않도록 했다. 새 공개 집계도 같은 `cache/published/housing/`에 보존하고 다음 배포가 읽는다. raw XLS/CSV는 매번 다시 읽으므로 별도 Actions 캐시를 요구하지 않는다.

```sh
python3 -m pip install -r requirements.txt
python3 scripts/housing_pipeline.py
python3 scripts/housing_moveins.py
cp cache/published/housing/pipeline.json.gz data/pipeline.json.gz
cp cache/published/housing/moveins.json.gz data/moveins.json.gz
python3 scripts/market_overview.py
```

기준일이 다른 실적·전망을 한 지표로 합산하지 않는다. 실제 입주 확인·신고 자료가 추가되면 별도 공급원을 만들고 정의와 공표 범위를 구분한다.


## 주간·월간 계산 모듈

`scripts/market_analysis.js`는 DOM·브라우저 저장소·통신에 의존하지 않는 공통 계산 모듈이다. 주간 상승률·2021~22 고점·국면·심리 정렬/백분위·이후 상승률·사이클 저점·확산도, 월간 변동률·날짜 정렬·단위 환산을 담당한다. HTML 템플릿은 선택 상태와 계산 함수 호출, 차트·표 표시를 담당한다. 화면용 정렬과 요약 문장 조립은 템플릿에 유지한다.

두 Python 생성기는 `/*ANALYSIS*/` 자리에 같은 모듈을 포함한다. 별도 JS 요청이 없어 날짜별 보관 HTML과 직접 파일 열기도 동작한다. 생성된 HTML에 직접 수정하지 않고 모듈과 템플릿을 수정한다. Node.js 22 이상을 설치해 계산 검사를 실행한다(추가 npm 패키지는 필요 없다). Actions와 자동 배포 명령도 같은 검사를 실행한다.

```sh
node --test tests/market_analysis.test.cjs
python3 -m unittest discover -s tests -v
python3 scripts/kb_dashboard.py
python3 scripts/kb_monthly_dashboard.py
```

이번 분리는 기존 산식과 표시 결과를 유지한다. 주간은 마지막 공통 기준주의 관측을 요구하고, 월간은 마지막 유효 관측을 기준으로 월 위치를 비교한다. 결측 비교 월을 건너뛰지 않는다. 심리 구간 대표값은 기존의 짝수 표본 상위 중앙값 관행을 유지했다. 산식·임계값을 바꾸는 경우 `tests/market_analysis.test.cjs`와 `docs/indicators.md`를 함께 변경하고 수치 변경을 별도 검토한다.


## 자료 상태 표시

`data_health.py`는 자료 기준기간과 마지막 완전한 집계의 수집일을 따로 점검한다. 운영 기준은 주간 14일, 월간 2개월, API·공급 집계 수집 3일 초과다. 한국 시간의 화면 생성일을 기준으로 판정하고, KB 수집일 미기록과 결측·잘못된 날짜를 공개한다. 새로 수집했다는 이유로 오래된 기준월을 최신이라고 표시하지 않는다.

`overview.html` 상단에서 확인 필요 자료 개수를 보고, 아래 자료 기준일·갱신 점검 표와 CSV에서 기준기간·수집일·사유·확인 방법을 확인한다. 카드의 개별 지역 가용 기간과 전체 자료의 최신 기간은 다를 수 있다. 입주예정은 공식 전망 기준일·현재 월을 포함한 12개월 범위·수집일을 확인하며 예정월을 실제 관측일로 비교하지 않는다.

이는 화면 운영 기준으로 공식 공표 일정이나 최근 Actions 수집 성공을 뜻하지 않는다. 화면은 정적이며 표시된 점검일 이후 상태를 자동 재조회하지 않는다. 기존 Actions 신선도 메일 점검 범위(주간·월간·실거래)는 유지하며 날짜 판정은 한국 시간으로 통일한다.


## 관심 지역 비교 설정

종합 화면에서 시장 흐름·임대차/부담·공급/입주 묶음 또는 전체 17지표 중 1~6개를 선택한다. 관심 지역 중 기준 지역을 정하고 차이 표시를 켠다. 선택 지표·기준 지역·차이 표시를 브라우저에 저장하고 공유 주소의 `cols`, `base`, `delta`에도 넣는다. 관심 지역을 제거하면 유효한 첫 비교 지역으로 기준을 바꾼다.

`scripts/overview_comparison.js`는 표시와 분리된 차이 계산 함수다. 값·기간·단위·해당 지역 권역이 모두 확인될 때만 차이를 계산하고, 상위/통합 권역 대체값과 다른 기준기간은 사유를 공개한다. % 지표는 %p, HAI는 점, 물량은 호 차이다. 금리는 전국 공통값이다. 지역 크기·단지 구성을 보정하거나 투자 순위를 만들지 않는다. 원값은 차이 보류 시에도 표시한다.

지역 비교 CSV는 선택 지표의 원값·기간·권역, 기준 지역의 값·기간·권역, 차이와 보류 사유를 담는다. 기존 관심 지역 CSV는 17지표 전체를 내보낸다. 비교 계산 모듈도 종합 HTML에 포함하고 자동 배포 시 공개 포함 내용을 확인한다.

```sh
node --test tests/market_analysis.test.cjs tests/overview_comparison.test.cjs
```


## 실거래 조건 공유·월별 CSV

실거래 화면은 `gu`, `type`, `area`, `age`, `low`, `lowType`, `sort4`를 브라우저 저장소와 공유 주소에 담는다. 주소에 지정된 조건을 우선 적용하고 지원하지 않는 값은 기본값으로 복원한다. 기존 지역만 지정한 링크와 서울 구 이름 링크도 지원한다. 클립보드 접근이 실패하면 직접 복사할 주소를 표시한다.

선택 조건 월별 CSV는 해당 지역·유형·면적·연식의 24개월 집계, 가격/㎡당 가격 표본, 중위·분포·수집일을 담는다. 가격 표본 10건 미만은 가격·분포를 비우고 수집 누락은 빈 값과 상태로 표시한다. 월 중위값을 합쳐 3개월 중위값으로 만들지 않는다. 조건 자료 로딩·실패 상태에서는 CSV를 막고 재시도 버튼을 제공한다. 원계약이나 새로운 API 응답을 내보내지 않는다.


## 실거래 조건 자료 로딩

`profile_loader.js`는 진행 중인 같은 조건 요청을 공유하고 검증된 응답만 브라우저 캐시에 저장한다. 지역·유형을 바꾸는 동안 면적/연식 조건이 같으면 요청을 추가하지 않는다. 요청은 15초 후 중단하며 실패·시간 초과·형식 오류는 캐시하지 않아 재시도할 수 있다. 시간 초과 후 늦게 온 응답은 재시도 결과를 덮어쓰지 않는다.

응답의 유형·지역·월별/3개월 배열 길이, 숫자/결측 형식과 표본 건수 관계를 확인한다. 화면의 요청 순번으로 마지막 선택만 적용하고 CSV는 실제 적용 조건과 일치할 때 활성화한다. 모듈은 생성 HTML에 포함되어 별도 JS 요청이 필요 없다.

```sh
node --test tests/market_analysis.test.cjs tests/overview_comparison.test.cjs tests/profile_loader.test.cjs
```


## 실거래 지역 비교 내보내기

지역별 비교표는 전국 선택 시 17개 시도, 시도·시군구 선택 시 해당 시도의 시군구를 표시한다. 선택 유형·면적·연식과 현재 정렬을 CSV에도 적용한다. 최근 3개 완결월과 전년 같은 3개월의 실제 거래를 합친 중위값을 사용하며 월 중위값의 평균을 만들지 않는다.

표에는 양쪽 기간의 ㎡당 가격 표본과 비교 상태를 표시한다. 지역 비교 CSV에는 두 기간·거래 건수·가격/㎡당 표본·중위값·증감률·보류 사유·수집일을 담는다. 수집 누락·표본 부족·전년 0건의 비율은 빈 값으로 내보내고 사유를 구분한다. 지역 크기·단지·층·입지 구성은 보정하지 않는다. 기존 월별 CSV와 같은 인코딩·다운로드 함수를 사용한다.
