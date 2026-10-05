# 구글 드라이브에서 KB 엑셀 읽기 설정

국면판 프로그램이 구글 드라이브 폴더에서 최신 `YYYYMMDD_주간시계열.xlsx`를 직접 내려받도록 하는 설정입니다. 처음 한 번만 하면 됩니다(약 15~20분).

구조: **서비스 계정**(프로그램 전용 구글 계정)을 만들고, 드라이브 폴더를 그 계정에 "뷰어"로 공유합니다. 프로그램은 그 계정의 키 파일로 폴더를 읽기만 합니다.

## 1. Google Cloud 프로젝트 만들기

1. https://console.cloud.google.com 에 구글 계정으로 로그인합니다.
2. 상단 프로젝트 선택 → **새 프로젝트** → 이름 예: `house-kb` → 만들기.

## 2. Google Drive API 켜기

1. 왼쪽 메뉴 **API 및 서비스 → 라이브러리**.
2. `Google Drive API` 검색 → **사용**.

## 3. 서비스 계정과 키 만들기

1. **API 및 서비스 → 사용자 인증 정보 → 사용자 인증 정보 만들기 → 서비스 계정**.
2. 이름 예: `kb-reader` → 만들고 계속. 역할은 지정하지 않아도 됩니다 → 완료.
3. 만든 서비스 계정을 누르고 **키 → 키 추가 → 새 키 만들기 → JSON** → 만들기.
4. 내려받은 JSON 파일을 프로젝트의 `secrets/kb-drive-sa.json`으로 옮깁니다.
5. 서비스 계정의 이메일 주소(`kb-reader@house-kb.iam.gserviceaccount.com` 형태)를 복사해 둡니다.

> `secrets/` 폴더는 `.gitignore`에 들어 있어 Git에 올라가지 않습니다. 키 파일은 비밀번호와 같으니 메일·메신저로 보내지 마세요.

## 4. 드라이브 폴더 공유

1. 구글 드라이브에 폴더를 만듭니다. 예: `house/kbdata`.
2. 폴더 **공유** → 3-5에서 복사한 서비스 계정 이메일 입력 → 권한 **뷰어** → 보내기.
3. 폴더를 열었을 때 주소창의 `https://drive.google.com/drive/folders/` 뒤 문자열이 **폴더 id**입니다.

## 5. 프로젝트에 폴더 id 저장

`secrets/drive.json` 파일을 만듭니다.

```json
{
  "folder_id": "여기에_폴더_id"
}
```

환경변수로 줄 수도 있습니다(환경변수가 우선).

```bash
export KB_DRIVE_FOLDER_ID="여기에_폴더_id"
export KB_SA_KEY="/경로/kb-drive-sa.json"   # 기본값 secrets/kb-drive-sa.json
```

## 6. 확인과 사용

```bash
python3 -m pip install --user -r requirements.txt   # 처음 한 번
python3 scripts/kb_drive.py --list                   # 폴더의 파일 목록이 보이면 성공
python3 scripts/kb_dashboard.py --drive              # 최신 파일 받기 + 국면판 생성
```

## 매주·매월 할 일

KB부동산에서 받은 엑셀을 파일 이름 그대로 드라이브 폴더에 올립니다. 이름 앞의 날짜로 최신 파일을 고릅니다.

| 자료 | 파일 이름 예 | 주기 | 화면 |
|---|---|---|---|
| 주간 아파트 | `20260928_주간시계열.xlsx` | 매주 | `index.html` 주간 아파트 국면판 |
| 월간 주택 | `202610_월간 주택 시계열.xlsx` | 매월 | `monthly.html` 월간 주택 시장판 |
| 월간 오피스텔 | `202610_월간 오피스텔 시계열.xlsx` | 매월 | `monthly.html`의 오피스텔 구역 (없으면 그 구역만 비어 있음) |

이 컴퓨터에서 직접 만들 때:

```bash
python3 scripts/kb_dashboard.py --drive           # 주간
python3 scripts/kb_monthly_dashboard.py --drive   # 월간 주택 + 오피스텔
python3 scripts/kb_drive.py --list                # 드라이브에 있는 KB 파일 목록
```

## 동작 방식

- 폴더에서 이름에 `YYYYMMDD_주간시계열`이 들어간 엑셀(또는 구글 시트로 변환된 파일)만 찾고, 날짜가 가장 늦은 파일을 고릅니다.
- `kbdata/`에 같은 이름·같은 크기의 파일이 있으면 다시 받지 않습니다.
- 구글 시트로 변환된 파일은 엑셀로 내보내서 받습니다. 원본 엑셀 그대로 올리는 것을 권장합니다(변환하면 서식이 달라질 수 있음).

## 문제 해결

| 메시지 | 원인 |
|---|---|
| 드라이브 폴더 id가 없습니다 | 5단계 `secrets/drive.json`이 없거나 `folder_id`가 비어 있음 |
| 서비스 계정 키 파일이 없습니다 | 3-4단계 키 파일 위치가 다름 |
| 'YYYYMMDD_주간시계열' 이름의 엑셀이 없습니다 | 폴더를 서비스 계정과 공유하지 않았거나, 파일 이름 형식이 다름 |
| `HttpError 403 ... Drive API has not been used` | 2단계 Drive API를 켜지 않음 |
| `HttpError 404 File not found` | 폴더 id가 틀렸거나 공유가 안 됨 |

## GitHub Actions로 자동 게시 (GitHub Pages)

`.github/workflows/dashboard.yml`이 매일 09:00(한국 시간)에 드라이브의 최신 파일로 주간 국면판(`https://hanspak.github.io/house/`)과 월간 주택 시장판(`https://hanspak.github.io/house/monthly.html`)을 만들어 올립니다. 드라이브에 새 파일을 올린 뒤 바로 보고 싶으면 **Actions → 국면판 갱신 → Run workflow**를 누릅니다.

### 처음 한 번 설정

1. **Secrets 등록**: 저장소 **Settings → Secrets and variables → Actions → New repository secret**
   - `KB_SA_KEY_JSON`: `secrets/kb-drive-sa.json` 파일 내용 전체 (`{`부터 `}`까지)
   - `KB_DRIVE_FOLDER_ID`: 드라이브 폴더 id
2. **Pages 켜기**: 저장소 **Settings → Pages → Build and deployment → Source**를 **GitHub Actions**로 선택

### 주의

- 무료 GitHub Pages 주소는 누구나 볼 수 있습니다. 화면에는 KB 공개 통계만 들어 있고, 키와 폴더 id는 들어가지 않습니다.
- 키는 GitHub Secrets에만 저장되고, 실행 로그에는 `***`로 가려집니다. 실행이 끝나면 작업 공간의 키 파일도 지웁니다.
- 실행이 실패하면 Actions 탭에서 빨간 표시를 눌러 로그를 보면 됩니다. 메시지별 원인은 위의 "문제 해결" 표와 같습니다.
- **자료가 오래되면 알림 메일이 옵니다.** 주간 기준일이 14일, 월간 기준월이 2개월을 넘으면 화면은 그대로 올리고 마지막 `freshness` 작업만 실패시킵니다. 새 파일을 올리면 다음 실행부터 사라집니다. 현재 기준일은 `https://hanspak.github.io/house/status.json`에서도 볼 수 있습니다.
- **KB가 엑셀 구조를 바꾸면** 추출 단계의 점검(지역 수, 날짜 연속성 등)이 실패해 배포하지 않습니다. 이때는 이전 화면이 그대로 남고 실패 메일이 옵니다.

## 실거래·거래량·금리용 API 키 (`trades.html`)

실거래 화면에서 전국·17개 시·도와 시군구를 선택할 수 있습니다. 금리는 전국 공통 자료입니다. 처음 전국 자료를 수집할 때는 서울만 수집할 때보다 API 요청 수와 시간이 늘어납니다. 이후 실행은 기존 월별 캐시를 재사용합니다. 일부 지역·월의 수집이 실패하면 해당 통계를 비우고 화면에 안내합니다.

로컬 갱신: `python3 scripts/kb_trades_dashboard.py`. 캐시만으로 화면을 다시 생성하려면 `python3 scripts/kb_trades_dashboard.py --no-fetch`를 실행합니다. 실거래 수집 병렬 수는 `python3 scripts/molit_trades.py --workers 4`로 조정할 수 있습니다.

| Secret 이름 | 발급처 | 로컬 파일 키 |
|---|---|---|
| `DATA_GO_KR_KEY` | 공공데이터포털 일반 인증키(**Decoding**). 아파트 매매 상세·연립다세대 매매·오피스텔 매매 실거래 API 활용 신청 필요 | `data_go_kr` |
| `RONE_KEY` | 한국부동산원 R-ONE Open API 인증키 | `rone` |
| `ECOS_KEY` | 한국은행 ECOS Open API 인증키 | `ecos` |

- GitHub: 저장소 **Settings → Secrets and variables → Actions**에 위 세 이름으로 등록합니다. 없으면 `trades.html`은 "키 등록 필요" 안내 페이지로 올라갑니다.
- 이 컴퓨터: `secrets/api_keys.json`에 `{"data_go_kr": "...", "rone": "...", "ecos": "..."}` 형식으로 둡니다(Git 제외).
- 호출량: 첫 실행은 실거래 약 1,800회(서울 25개 구 × 24개월 × 3유형), 이후에는 최근 3개월만 다시 받아 하루 약 230회입니다. 지난 달 응답은 GitHub Actions 캐시(`cache/molit`)에 보관합니다.
- 공공데이터포털이 요청 과다(429)로 막으면 기다렸다 다시 시도하고, 그래도 실패한 달은 다음 실행 때 다시 받습니다(화면 위쪽에 실패 건수 표시).
