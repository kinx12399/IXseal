"""PostgreSQL 연결 풀과 마이그레이션."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_pool: ConnectionPool | None = None


def open_pool(url: str, *, max_size: int = 10) -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(url, min_size=1, max_size=max_size, kwargs={"row_factory": dict_row}, open=True)
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def connection() -> Iterator[psycopg.Connection]:
    """트랜잭션 하나. 예외 없이 끝나면 커밋, 예외면 롤백."""
    if _pool is None:
        raise RuntimeError("DB 풀이 열려 있지 않습니다")
    with _pool.connection() as conn:
        yield conn


def migrate(url: str) -> list[str]:
    """migrations/*.sql 을 순서대로 한 번씩 적용하고, 템플릿이 없으면 기본 템플릿을 넣는다."""
    from .seed import seed_templates

    applied: list[str] = []
    with psycopg.connect(url, row_factory=dict_row) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        done = {r["version"] for r in conn.execute("SELECT version FROM schema_migrations")}
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.stem in done:
                continue
            with conn.transaction():
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.stem,))
            applied.append(path.stem)
        with conn.transaction():
            seed_templates(conn)
    return applied
