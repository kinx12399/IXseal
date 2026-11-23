#!/usr/bin/env bash
# IXseal 업데이트 (root): 코드 받기 → 의존성 → 마이그레이션 → 재시작
set -euo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV=/opt/ixseal/venv
[[ $EUID -eq 0 ]] || { echo "root로 실행하세요 (sudo)" >&2; exit 1; }

git -C "$APP_DIR" pull --ff-only
chmod -R o+rX "$APP_DIR"
"$VENV/bin/pip" install -q -r "$APP_DIR/requirements.txt"
runuser -u ixseal -- bash -c "cd '$APP_DIR' && set -a && . /etc/ixseal/ixseal.env && set +a && PYTHONDONTWRITEBYTECODE=1 '$VENV/bin/python' -m ixseal migrate"
install -m 0644 "$APP_DIR"/deploy/systemd/*.service "$APP_DIR"/deploy/systemd/*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl restart ixseal-public ixseal-admin
sleep 2
curl -fsk https://127.0.0.1/healthz && echo " ← 고객용" && curl -fsk https://127.0.0.1:8443/healthz && echo " ← 관리용"
