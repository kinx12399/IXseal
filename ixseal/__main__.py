"""운영 명령.

    python -m ixseal migrate                 스키마 적용 + 기본 템플릿 (최초 1회)
    python -m ixseal init-kek <경로>          KEK 파일 생성 (없을 때만)
    python -m ixseal rotate-kek <경로>        새 KEK를 추가 (이후 새 전달은 새 키로 암호화)
    python -m ixseal maintenance             만료 폐기·정리 작업 (systemd timer가 5분마다 실행)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .config import get_settings


def _init_kek(path: Path) -> int:
    from .crypto import new_kek_line

    if path.exists():
        print(f"이미 있습니다: {path} (덮어쓰지 않습니다)")
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o440)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("# IXseal KEK. 이 파일을 잃으면 저장된 내용을 복호화할 수 없습니다. DB 백업과 따로 보관하세요.\n")
        fh.write(new_kek_line(1) + "\n")
    print(f"KEK를 만들었습니다: {path}")
    return 0


def _rotate_kek(path: Path) -> int:
    from .crypto import KeyRing, new_kek_line

    ring = KeyRing.load(path)
    new_id = ring.current_id + 1
    st = path.stat()
    content = path.read_text(encoding="utf-8").rstrip("\n") + "\n" + new_kek_line(new_id) + "\n"
    # 읽기 전용(0440) 파일이므로 새 파일을 같은 소유자·권한으로 만든 뒤 바꿔 끼운다
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, st.st_mode & 0o777)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(content)
    if hasattr(os, "chown"):
        os.chown(tmp, st.st_uid, st.st_gid)
    os.replace(tmp, path)
    print(f"KEK {new_id}를 추가했습니다. 서비스를 재시작하면 새 전달부터 적용됩니다.")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m ixseal")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    k = sub.add_parser("init-kek")
    k.add_argument("path", type=Path)
    r = sub.add_parser("rotate-kek")
    r.add_argument("path", type=Path)
    sub.add_parser("maintenance")
    args = p.parse_args(argv)
    s = get_settings()

    if args.cmd == "migrate":
        from .db import migrate

        applied = migrate(s.database_url)
        print("적용:", ", ".join(applied) if applied else "없음 (최신)")
        return 0
    if args.cmd == "init-kek":
        return _init_kek(args.path)
    if args.cmd == "rotate-kek":
        return _rotate_kek(args.path)
    if args.cmd == "maintenance":
        import psycopg
        from psycopg.rows import dict_row

        from .service import run_maintenance

        with psycopg.connect(s.database_url, row_factory=dict_row) as conn:
            counts = run_maintenance(conn, session_minutes=s.reveal_session_minutes, retention_days=s.retention_days)
        if any(counts.values()):
            print(" ".join(f"{k}={v}" for k, v in counts.items()))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
