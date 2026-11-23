# IXseal

IXcloud 고객에게 계정정보(콘솔 계정, VM 접속 정보·키 파일, DB 계정 등)를 메일 본문 대신 **만료되는 열람 링크**로 전달하는 서비스입니다.

- 엔지니어: 사무실 IP만 열린 관리 화면(8443)에서 템플릿을 골라 입력 → **봉인** → 링크와 메일 안내문을 복사해 기존 메일로 보냅니다.
- 고객: 링크를 열고 [계정정보 보기]를 누르면 확인할 수 있습니다. 기한(1시간~7일)이 지나거나 폐기 조건(1회 열람·고객 확인)을 충족하면 내용이 삭제됩니다.
- 내용과 파일은 AES-256-GCM 봉투 암호화로 저장하며, 엔지니어 화면에서도 다시 볼 수 없습니다.

| 문서 | 내용 |
| --- | --- |
| [docs/DESIGN.md](docs/DESIGN.md) | 설계 (흐름, 정책, 암호화, 데이터, 보존 기간) |
| [docs/UI.md](docs/UI.md) | UI/UX 원칙과 화면 구성 |
| [docs/DEPLOY.md](docs/DEPLOY.md) | VM 설치·운영·운영 전환, 로컬 개발 |

## 구조

```text
ixseal/
  public_app.py   고객용 앱 (443)  — /s/<토큰>, 열람, 파일 받기, 고객 폐기
  admin_app.py    관리용 앱 (8443) — 전달 목록·등록·상세, 템플릿, 미리보기 API
  service.py      핵심 로직 (등록·열람·폐기·회수·재발급·정리 작업)
  crypto.py       봉투 암호화, 링크 토큰
  views.py        고객 화면 뷰 모델 (실제 화면과 미리보기가 공유)
  templates/      Jinja (customer/_macros.html 을 두 앱이 함께 사용)
  static/         CSS·JS·아이콘·Pretendard 폰트 (외부 CDN 없음)
  migrations/     SQL 마이그레이션
deploy/           install.sh, update.sh, Nginx, systemd, 백업
tests/            pytest (단위 + PostgreSQL 흐름)
```
