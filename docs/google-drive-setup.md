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

## 매주 할 일

1. KB부동산에서 받은 엑셀을 파일 이름 그대로(`20260928_주간시계열.xlsx` 등) 드라이브 폴더에 올립니다.
2. `python3 scripts/kb_dashboard.py --drive`를 실행합니다.

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
