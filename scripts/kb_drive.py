"""구글 드라이브 폴더에서 최신 KB 시계열 엑셀(주간·월간 주택·월간 오피스텔)을 kbdata/로 내려받는다.

서비스 계정으로 Drive API(읽기 전용)를 쓴다. 설정 방법은 docs/google-drive-setup.md 참고.

설정값 (환경변수가 있으면 우선, 없으면 secrets/drive.json):
  KB_DRIVE_FOLDER_ID  엑셀을 올리는 드라이브 폴더 id
  KB_SA_KEY           서비스 계정 키 JSON 경로 (기본 secrets/kb-drive-sa.json)

사용법:
  python3 scripts/kb_drive.py                    # 최신 주간 파일 받기 (이미 있으면 건너뜀)
  python3 scripts/kb_drive.py --kind monthly     # 최신 월간 주택 파일 (officetel: 월간 오피스텔)
  python3 scripts/kb_drive.py --list             # 폴더의 KB 파일 목록만 보기
"""
import argparse
import io
import json
import os
import re
import sys
import unicodedata
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)  # Python 3.9 지원 종료 경고

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
GSHEET = "application/vnd.google-apps.spreadsheet"
# 종류: (파일 이름 패턴, 내려받을 때 쓸 이름). 이름 안 공백은 있어도 없어도 인식한다.
KINDS = {
    "weekly": (re.compile(r"(\d{8})_주간\s*시계열"), "{asof}_주간시계열.xlsx"),
    "monthly": (re.compile(r"(\d{6})_월간\s*주택\s*시계열"), "{asof}_월간 주택 시계열.xlsx"),
    "officetel": (re.compile(r"(\d{6})_월간\s*오피스텔\s*시계열"), "{asof}_월간 오피스텔 시계열.xlsx"),
}
LABELS = {"weekly": "주간", "monthly": "월간 주택", "officetel": "월간 오피스텔"}


def config():
    cfg = {}
    path = os.path.join(ROOT, "secrets", "drive.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    folder = os.environ.get("KB_DRIVE_FOLDER_ID") or cfg.get("folder_id")
    key = os.environ.get("KB_SA_KEY") or cfg.get("key_file") or os.path.join(ROOT, "secrets", "kb-drive-sa.json")
    if not os.path.isabs(key):
        key = os.path.join(ROOT, key)
    if not folder:
        sys.exit("드라이브 폴더 id가 없습니다. KB_DRIVE_FOLDER_ID 환경변수나 secrets/drive.json의 folder_id를 설정하세요.")
    if not os.path.exists(key):
        sys.exit(f"서비스 계정 키 파일이 없습니다: {key}")
    return folder, key


def service(key):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(key, scopes=SCOPES)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def list_files(svc, folder, kind="weekly"):
    """폴더 안의 해당 종류 KB 엑셀/구글시트를 기준일 내림차순으로."""
    q = f"'{folder}' in parents and trashed = false and (mimeType = '{XLSX}' or mimeType = '{GSHEET}')"
    files, token = [], None
    while True:
        r = svc.files().list(q=q, fields="nextPageToken, files(id, name, mimeType, size, modifiedTime)",
                             pageSize=200, pageToken=token,
                             supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        files += r.get("files", [])
        token = r.get("nextPageToken")
        if not token:
            break
    out = []
    for f in files:
        # Mac에서 올린 파일은 한글 이름이 자모 분리형(NFD)이라 정규화 후 비교한다.
        m = KINDS[kind][0].search(unicodedata.normalize("NFC", f["name"]))
        if m:
            f["asof"], f["kind"] = m.group(1), kind
            out.append(f)
    return sorted(out, key=lambda f: (f["asof"], f["modifiedTime"]), reverse=True)


def download(svc, f, dest_dir):
    from googleapiclient.http import MediaIoBaseDownload

    name = KINDS[f["kind"]][1].format(asof=f["asof"])
    dest = os.path.join(dest_dir, name)
    # 같은 이름·같은 크기면 다시 받지 않는다 (구글시트는 크기 정보가 없어 항상 받음).
    if os.path.exists(dest) and f.get("size") and os.path.getsize(dest) == int(f["size"]):
        print(f"이미 있음: {dest}")
        return dest
    if f["mimeType"] == GSHEET:
        req = svc.files().export_media(fileId=f["id"], mimeType=XLSX)
    else:
        req = svc.files().get_media(fileId=f["id"], supportsAllDrives=True)
    tmp = dest + ".part"
    with io.FileIO(tmp, "wb") as fh:
        dl = MediaIoBaseDownload(fh, req, chunksize=8 * 1024 * 1024)
        done = False
        while not done:
            _, done = dl.next_chunk()
    os.replace(tmp, dest)
    print(f"내려받음: {f['name']} → {dest}")
    return dest


def fetch_latest(kind="weekly", required=True):
    """해당 종류의 최신 파일을 kbdata/에 받아 그 경로를 돌려준다. required=False면 없을 때 None."""
    folder, key = config()
    svc = service(key)
    files = list_files(svc, folder, kind)
    if not files:
        if not required:
            print(f"드라이브에 {LABELS[kind]} 파일이 없어 건너뜀")
            return None
        example = KINDS[kind][1].format(asof="20260921" if kind == "weekly" else "202609")
        sys.exit(f"드라이브 폴더에 {LABELS[kind]} 엑셀이 없습니다(예: {example}). 폴더를 서비스 계정과 공유했는지도 확인하세요.")
    dest_dir = os.path.join(ROOT, "kbdata")
    os.makedirs(dest_dir, exist_ok=True)
    return download(svc, files[0], dest_dir)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--list", action="store_true", help="파일 목록만 보기")
    ap.add_argument("--kind", choices=list(KINDS), default="weekly", help="받을 파일 종류")
    args = ap.parse_args()
    if args.list:
        folder, key = config()
        svc = service(key)
        for kind in KINDS:
            for f in list_files(svc, folder, kind):
                size = f"{int(f['size']) / 1e6:.1f}MB" if f.get("size") else "구글시트"
                print(f"{LABELS[kind]:7s} {f['asof']}  {unicodedata.normalize('NFC', f['name'])}  {size}  수정 {f['modifiedTime'][:10]}")
    else:
        fetch_latest(args.kind)
