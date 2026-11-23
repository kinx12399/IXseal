#!/usr/bin/env bash
# IXseal 설치 (Ubuntu 24.04, root). 여러 번 실행해도 안전하다 (있는 키·인증서·설정은 덮어쓰지 않는다).
#
#   git clone https://github.com/kinx12399/IXseal.git /opt/ixseal/app
#   sudo bash /opt/ixseal/app/deploy/install.sh --server-name <VM 공인 IP 또는 도메인>
#
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV=/opt/ixseal/venv
ETC=/etc/ixseal
SERVER_NAME=""
ENV_LABEL="DEV"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --server-name) SERVER_NAME="$2"; shift 2 ;;
    --env-label) ENV_LABEL="$2"; shift 2 ;;
    *) echo "알 수 없는 옵션: $1" >&2; exit 2 ;;
  esac
done
[[ $EUID -eq 0 ]] || { echo "root로 실행하세요 (sudo)" >&2; exit 1; }
[[ -n "$SERVER_NAME" ]] || { echo "--server-name <공인 IP 또는 도메인> 이 필요합니다" >&2; exit 2; }
[[ "$APP_DIR" == "/opt/ixseal/app" ]] || echo "주의: 앱 경로가 /opt/ixseal/app 이 아닙니다 ($APP_DIR). systemd 유닛은 /opt/ixseal/app 기준입니다."

step() { printf '\n\033[1;32m▶ %s\033[0m\n' "$*"; }

step "패키지 설치"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq nginx postgresql python3-venv openssl >/dev/null

step "서비스 계정 ixseal"
id ixseal >/dev/null 2>&1 || useradd --system --home-dir /opt/ixseal --no-create-home --shell /usr/sbin/nologin ixseal
chmod -R o+rX "$APP_DIR"   # ixseal·www-data(정적 파일)가 읽을 수 있게
chmod 755 "$APP_DIR/deploy/backup.sh"

step "Python 가상환경"
[[ -x "$VENV/bin/python" ]] || python3 -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r "$APP_DIR/requirements.txt"

step "PostgreSQL 역할·DB (유닉스 소켓 peer 인증)"
runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='ixseal'" | grep -q 1 \
  || runuser -u postgres -- psql -qc "CREATE ROLE ixseal LOGIN"
runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='ixseal'" | grep -q 1 \
  || runuser -u postgres -- createdb -O ixseal ixseal

step "설정·KEK ($ETC)"
install -d -m 0750 -o root -g ixseal "$ETC"
if [[ ! -f "$ETC/kek" ]]; then
  (cd "$APP_DIR" && PYTHONDONTWRITEBYTECODE=1 "$VENV/bin/python" -m ixseal init-kek "$ETC/kek")
  NEW_KEK=1
fi
chown root:ixseal "$ETC/kek"; chmod 0440 "$ETC/kek"
if [[ ! -f "$ETC/ixseal.env" ]]; then
  sed -e "s|__SERVER_NAME__|$SERVER_NAME|g" -e "s|^IXSEAL_ENV_LABEL=.*|IXSEAL_ENV_LABEL=$ENV_LABEL|" \
    "$APP_DIR/deploy/ixseal.env.example" > "$ETC/ixseal.env"
fi
chown root:ixseal "$ETC/ixseal.env"; chmod 0640 "$ETC/ixseal.env"

step "TLS 인증서"
install -d -m 0750 -o root -g root "$ETC/tls"
if [[ ! -f "$ETC/tls/cert.pem" ]]; then
  if [[ "$SERVER_NAME" =~ ^[0-9.]+$ ]]; then SAN="IP:$SERVER_NAME"; else SAN="DNS:$SERVER_NAME"; fi
  openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 397 \
    -subj "/CN=$SERVER_NAME/O=IXseal (dev self-signed)" -addext "subjectAltName=$SAN" \
    -keyout "$ETC/tls/key.pem" -out "$ETC/tls/cert.pem" 2>/dev/null
  echo "자체 서명 인증서를 만들었습니다 (개발용). 운영 전환 시 $ETC/tls/{cert,key}.pem 을 와일드카드 인증서로 바꾸세요."
fi
chmod 0600 "$ETC/tls/key.pem"; chmod 0644 "$ETC/tls/cert.pem"

step "DB 마이그레이션"
runuser -u ixseal -- bash -c "cd '$APP_DIR' && set -a && . '$ETC/ixseal.env' && set +a && PYTHONDONTWRITEBYTECODE=1 '$VENV/bin/python' -m ixseal migrate"

step "Nginx"
install -d -m 0755 -o root -g adm /var/log/ixseal
install -d -m 0755 /var/www/acme
install -m 0644 "$APP_DIR/deploy/nginx/ixseal-proxy.conf" /etc/nginx/snippets/ixseal-proxy.conf
sed -e "s|__SERVER_NAME__|$SERVER_NAME|g" -e "s|__APP_DIR__|$APP_DIR|g" \
  "$APP_DIR/deploy/nginx/ixseal.conf" > /etc/nginx/sites-available/ixseal
ln -sf /etc/nginx/sites-available/ixseal /etc/nginx/sites-enabled/ixseal
rm -f /etc/nginx/sites-enabled/default
install -m 0644 "$APP_DIR/deploy/logrotate-ixseal" /etc/logrotate.d/ixseal
nginx -t
systemctl enable --now nginx >/dev/null
systemctl reload nginx

step "systemd 서비스·타이머"
install -d -m 0700 -o ixseal -g ixseal /var/backups/ixseal
install -m 0644 "$APP_DIR"/deploy/systemd/*.service "$APP_DIR"/deploy/systemd/*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now ixseal-public ixseal-admin ixseal-maintenance.timer ixseal-backup.timer >/dev/null
systemctl restart ixseal-public ixseal-admin

step "상태 확인"
for i in $(seq 1 20); do
  curl -fsk "https://127.0.0.1/healthz" >/dev/null 2>&1 && curl -fsk "https://127.0.0.1:8443/healthz" >/dev/null 2>&1 && break
  sleep 1
done
curl -fsk "https://127.0.0.1/healthz" && echo "  ← 고객용 443"
curl -fsk "https://127.0.0.1:8443/healthz" && echo "  ← 관리용 8443"

cat <<EOF

────────────────────────────────────────────────────────
 IXseal 설치 완료
   고객용  https://$SERVER_NAME/s/<토큰>
   관리용  https://$SERVER_NAME:8443/
 보안그룹: 443 전체 허용 / 8443·22 는 1.201.194.31/32 만 허용
EOF
if [[ "${NEW_KEK:-0}" == 1 ]]; then
cat <<EOF

 ⚠ 새 KEK를 만들었습니다: $ETC/kek
   이 파일을 잃으면 저장된 내용을 복호화할 수 없습니다. DB 백업과 '다른 곳'에 보관하세요.
EOF
fi
echo "────────────────────────────────────────────────────────"
