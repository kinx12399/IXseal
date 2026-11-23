#!/usr/bin/env bash
# IXseal DB 백업. 백업에는 암호문만 들어간다 — KEK(/etc/ixseal/kek)는 여기에 포함하지 않으며 따로 보관해야 한다.
set -euo pipefail
DIR=/var/backups/ixseal
KEEP_DAYS=7
f="$DIR/ixseal-$(date +%Y%m%d-%H%M).dump"
pg_dump --format=custom --no-owner --file="$f.tmp" ixseal
mv "$f.tmp" "$f"
find "$DIR" -maxdepth 1 -name 'ixseal-*.dump' -mtime +"$((KEEP_DAYS - 1))" -delete
echo "백업: $f"
