# IXseal 배포 (단일 VM, Ubuntu 24.04)

## 1. VM과 보안그룹

| 항목 | 값 |
| --- | --- |
| 사양 | 2 vCPU / 4 GB / 50 GB SSD (최소 1 / 2 / 30) |
| OS | Ubuntu 24.04 LTS |
| 보안그룹 | **443** 전체 허용 (고객) · **8443** `1.201.194.31/32` (관리) · **22** `1.201.194.31/32` (SSH) |
| 80 | 열지 않아도 된다. 공인 인증서를 ACME HTTP-01로 받을 때만 필요 |

## 2. 설치

```bash
sudo git clone https://github.com/kinx12399/IXseal.git /opt/ixseal/app
sudo bash /opt/ixseal/app/deploy/install.sh --server-name <VM 공인 IP>
```

`install.sh`가 하는 일 (여러 번 실행해도 안전하다. 이미 있는 키·인증서·설정은 덮어쓰지 않는다):

1. `nginx`, `postgresql`, `python3-venv` 설치
2. 서비스 계정 `ixseal`, 가상환경 `/opt/ixseal/venv`
3. PostgreSQL 역할·DB `ixseal` (유닉스 소켓 peer 인증, 외부 접속 없음)
4. `/etc/ixseal/kek` 생성 (root:ixseal 0440), `/etc/ixseal/ixseal.env` 생성 (예시: [deploy/ixseal.env.example](../deploy/ixseal.env.example))
5. 자체 서명 인증서 `/etc/ixseal/tls/` (IP SAN, 개발용)
6. DB 마이그레이션과 기본 템플릿
7. Nginx: 443(고객용)·8443(관리용), 로그 `/var/log/ixseal/`, logrotate 730일
8. systemd: `ixseal-public`, `ixseal-admin`, `ixseal-maintenance.timer`(5분), `ixseal-backup.timer`(매일 03:30)

설치가 끝나면:
- 관리: `https://<IP>:8443/`. 처음 접속하면 담당자 이름을 묻는다.
- 고객: 관리 화면에서 만든 `https://<IP>/s/<토큰>` 링크
- 자체 서명 인증서라 브라우저 경고가 나온다(개발 단계).

## 3. ⚠ KEK 보관

`/etc/ixseal/kek`를 잃으면 저장된 모든 내용을 복호화할 수 없다. 반대로 KEK와 DB 백업이 함께 유출되면 아직 폐기되지 않은 내용이 노출된다.
- KEK는 **DB 백업(`/var/backups/ixseal`)과 다른 곳**에 보관한다(예: 사내 비밀 저장소, 오프라인 매체).
- 키 교체: `sudo /opt/ixseal/venv/bin/python -m ixseal rotate-kek /etc/ixseal/kek` 실행 후 서비스를 재시작한다. 새 전달부터 새 키를 쓰고, 기존 전달은 옛 키로 복호화한다. 옛 키 줄은 모든 전달이 만료될 때까지(최대 7일) 지우지 않는다.

## 4. 업데이트

```bash
sudo bash /opt/ixseal/app/deploy/update.sh   # git pull → 의존성 → 마이그레이션 → 재시작
```

## 5. 운영 확인

```bash
systemctl status ixseal-public ixseal-admin
systemctl list-timers 'ixseal-*'
journalctl -u ixseal-public -u ixseal-admin -n 100
journalctl -u ixseal-maintenance -n 20      # 폐기 건수 출력
ls -l /var/backups/ixseal                   # 매일 백업 7일분
tail -f /var/log/ixseal/nginx-public.log
```

복원: `sudo -u ixseal pg_restore --clean --if-exists -d ixseal /var/backups/ixseal/ixseal-YYYYMMDD-HHMM.dump` (같은 KEK 필요)

## 6. 운영 전환 (도메인·인증서)

1. DNS: `seal.ixcloud.net` → VM 공인 IP
2. `*.ixcloud.net` 와일드카드 인증서를 `/etc/ixseal/tls/cert.pem`(전체 체인), `/etc/ixseal/tls/key.pem`으로 교체
3. `/etc/ixseal/ixseal.env`: `IXSEAL_PUBLIC_BASE_URL=https://seal.ixcloud.net`, `IXSEAL_ENV_LABEL=` (비움)
4. `/etc/nginx/sites-available/ixseal`의 `server_name`을 `seal.ixcloud.net`으로 변경
5. `sudo nginx -t && sudo systemctl reload nginx && sudo systemctl restart ixseal-public ixseal-admin`

이미 보낸 링크는 주소(호스트)가 바뀌므로, 전환 전에 보낸 링크가 있으면 재발급한다.

## 7. 로컬 개발·테스트

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
# PostgreSQL이 있으면 (CREATE DATABASE 권한 필요)
IXSEAL_TEST_DATABASE_URL=postgresql:///postgres pytest
# 로컬 실행
python -m ixseal init-kek ./local/kek
export IXSEAL_DATABASE_URL=postgresql:///ixseal_dev IXSEAL_KEK_FILE=./local/kek \
       IXSEAL_PUBLIC_BASE_URL=http://localhost:8001 IXSEAL_COOKIE_SECURE=false IXSEAL_ENV_LABEL=LOCAL
python -m ixseal migrate
uvicorn ixseal.public_app:app --port 8001 &
uvicorn ixseal.admin_app:app --port 8002
```
