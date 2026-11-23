"""테스트 공통.

DB 테스트는 PostgreSQL이 필요하다:
  - IXSEAL_TEST_DATABASE_URL=postgresql:///postgres  (CREATE DATABASE 권한 필요. 임시 DB를 만들고 지운다)
  - 또는 `pip install pgserver` (로컬 임시 PostgreSQL을 띄운다)
둘 다 없으면 DB 테스트는 건너뛴다.
"""

from __future__ import annotations

import os
import uuid

import pytest

from ixseal.crypto import KeyRing


@pytest.fixture(scope="session")
def admin_db_url(tmp_path_factory):
    url = os.environ.get("IXSEAL_TEST_DATABASE_URL")
    if url:
        yield url
        return
    try:
        import pgserver
    except ImportError:
        pytest.skip("PostgreSQL 없음: IXSEAL_TEST_DATABASE_URL을 지정하거나 pgserver를 설치하세요")
    srv = pgserver.get_server(str(tmp_path_factory.mktemp("pgdata")), cleanup_mode="stop")
    yield srv.get_uri()


@pytest.fixture(scope="session")
def db_url(admin_db_url):
    import psycopg
    from psycopg.conninfo import make_conninfo

    from ixseal import db

    name = f"ixseal_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(admin_db_url, autocommit=True) as c:
        c.execute(f'CREATE DATABASE "{name}"')
    url = make_conninfo(admin_db_url, dbname=name)
    db.migrate(url)
    yield url
    db.close_pool()
    with psycopg.connect(admin_db_url, autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture(scope="session")
def keyring():
    return KeyRing({1: os.urandom(32)})


@pytest.fixture(scope="session")
def settings(db_url):
    from ixseal.config import Settings

    return Settings(
        database_url=db_url,
        kek_file="/nonexistent",
        public_base_url="https://seal.test",
        env_label="TEST",
        cookie_secure=True,
        serve_static=True,
    )


@pytest.fixture(scope="session")
def pool(settings):
    from ixseal import db

    db.open_pool(settings.database_url)
    yield
    db.close_pool()


@pytest.fixture
def clean(pool):
    """테스트마다 데이터를 비우고 기본 템플릿을 다시 넣는다."""
    from ixseal import db
    from ixseal.seed import seed_templates

    with db.connection() as conn:
        conn.execute("TRUNCATE access_logs, reveal_sessions, secret_files, secrets, templates CASCADE")
        seed_templates(conn)


@pytest.fixture
def admin(clean, settings, keyring):
    from fastapi.testclient import TestClient

    from ixseal.admin_app import create_app

    with TestClient(create_app(settings, keyring), base_url="https://admin.test") as c:
        yield c


@pytest.fixture
def public(clean, settings, keyring):
    from fastapi.testclient import TestClient

    from ixseal.public_app import create_app

    with TestClient(create_app(settings, keyring), base_url="https://seal.test") as c:
        yield c
