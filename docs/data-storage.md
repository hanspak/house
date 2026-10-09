# 원자료 보관과 SQLite

이 문서는 2026-10-09 도입한 보관 계층을 설명한다. 대시보드는 계속 기존 게시 집계를 읽고, `storage/`는 로컬 분석·복원용으로만 사용한다. Git과 Pages에 올리지 않는다. 인증키·요청 URL·API 응답의 인증 관련 헤더는 보관하지 않는다.

## 위치와 내용

각 작업 폴더의 `storage/<자료>/` 아래에 저장한다. 자료는 trades, rents, supply, pipeline, moveins, extra다. Codex는 `.worktrees/codex/storage/`를 사용한다. 다른 worktree와 자동 동기화하지 않는다.

- `archive.sqlite3`: 파일 버전, 관측 이력, 개별 매매/전월세 기록.
- `blobs/<SHA256>.gz`: 내용 해시에 대응하는 압축 파일. 같은 내용은 재사용하고 기존 버전을 삭제하지 않는다.
- `write.lock`: 같은 자료의 수집 스레드·프로세스 쓰기를 직렬화한다. SQLite 연결은 작업마다 닫는다.

매매/전월세 보관 대상은 수집기가 필요한 항목을 추출한 JSON이다. API XML 응답 전체나 해제 거래의 상세 기록이 아니다. 해제 거래는 수집기에서 제외하므로 버전별 거래 목록 차이는 볼 수 있지만 변경 원인을 단정할 수 없다. 공급 XLSX/XLS·입주예정 CSV는 다운로드 파일을 보관하고 R-ONE/ECOS는 추출된 시계열 JSON을 보관한다.

캐시를 교체하기 전에 기존 파일도 보관한다. 신규 거래 응답은 보관 성공 후 월별 캐시에 반영한다. 보관 실패는 수집 실패로 처리해 정상 게시 집계의 교체를 막는다.

## SQLite 규격 1

| 테이블 | 내용 |
|---|---|
| snapshots | 자료 폴더 내 유형·지역 코드·기간·내용 해시·형식·행 수. 동일 버전 재삽입 방지 |
| observations | 해당 버전을 확인한 시각·API/다운로드/기존 캐시 이관 구분·캐시 수정 시각 |
| records | 매매/전월세 버전별 행 순서·계약일·전체 추출 행 JSON |

동일 응답 안의 같은 거래 여러 건은 각각의 ordinal로 보존한다. 개편 전후 지역 코드도 서로 다른 조회 범위로 보존하고 여기서 전국 중복 제거를 하지 않는다. 모든 버전의 records를 합산하면 과거 버전과 개편 코드가 중복 계산된다. 기존 전국 집계의 코드 중복 처리 규칙을 계속 사용해야 한다.

`observed_at`은 보관 시스템이 파일을 확인한 시각이다. cache_import의 `source_modified_at`은 기존 파일의 수정 시각이며 API 조회 시각이 아니다. 기존 파일에 없던 과거 수집일·변경 이력은 만들어 넣지 않는다. 기존 입주예정 CSV의 기준일은 이관 파일만으로 확정하지 않아 unknown으로 보관한다.

## 기존 자료 이관

자신의 작업 폴더에서 실행한다. 이관은 기존 파일을 읽기만 하고 새 보관 파일은 자신의 storage에 만든다. 같은 파일·내용·수정 시각을 다시 가져오면 관측 기록도 중복 생성하지 않는다.

```sh
python3 scripts/data_archive.py import-cache
# 통합 폴더의 기존 매매 캐시도 읽어 오려면
python3 scripts/data_archive.py import-cache --cache-root /Users/hanspak/project/house/cache
python3 scripts/data_archive.py status
python3 scripts/data_archive.py verify
```

`status`는 자료별 버전·기록·관측 건수와 기간을 표시한다. 버전 수와 records 수는 고유 계약 건수를 뜻하지 않는다. 매매/전월세 월별 캐시, 공급 파일, 입주 CSV, extra.json의 허용된 3개 시계열을 이관한다. 잘못된 거래 행이나 요청 월과 다른 계약일은 거부하며 재실행 가능한 방식으로 이미 정상 보관된 자료는 유지한다.

## 백업과 복원 확인

```sh
python3 scripts/data_archive.py backup --dest storage/backups/20261009
python3 scripts/data_archive.py verify --path storage/backups/20261009
```

백업은 자료별 SQLite backup API로 일관된 DB를 복사하고 그 DB가 참조하는 압축 파일·manifest를 함께 보관한다. 원본 파일 해시와 DB 무결성·외래키·거래 행 수를 검사한다. 기존 백업의 자료 폴더는 덮어쓰지 않는다. 자료 간 시각은 서로 다를 수 있으며 모든 자료를 한 순간에 고정한 전역 스냅샷은 아니다.

백업 폴더의 `<자료>/archive.sqlite3`는 직접 조회할 수 있다. 복원할 때는 수집을 멈추고 비어 있는 작업 폴더의 storage에 자료 폴더와 blobs를 함께 복사한 뒤 verify를 실행한다. 파일 경로만 복사하거나 DB만 복원하면 참조 파일이 누락된다.

## 운영 범위

정기/수동 Actions의 refresh는 storage/trades·extra, housing은 storage/rents·supply·pipeline·moveins를 각자 캐시로 보존한다. 코드 push에서는 API를 수집하지 않으므로 이번 코드 배포가 클라우드 원자료를 새로 수집하거나 로컬 DB를 업로드하지 않는다.

Actions 캐시는 영구 백업 저장소가 아니다. 로컬 storage도 PC 손실에 대비한 외부 백업이 아니므로 검증된 백업 폴더를 별도 디스크·장기 보관 공간에 복사하는 운영이 필요하다. 외부 보관 공간은 이번 단계에서 연결하지 않았다. 자동 삭제/기간 제한은 없으므로 디스크 사용량을 확인해야 한다. 다음 단계의 단지 분석·거래 구성 분석에서 이 보관 계층을 활용한다.
