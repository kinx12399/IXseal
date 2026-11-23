"""고객·관리 앱 흐름 테스트 (PostgreSQL 필요)."""

from __future__ import annotations

import json
import uuid

import pytest

from ixseal import db, service

H = {"X-IXseal": "1"}
KEY = b"-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----\n"


def delivery(policy="until_confirmed", *, key_files=True, **over):
    console = [
        {"label": "콘솔 주소", "type": "url", "value": "https://console.ixcloud.net", "required": True},
        {"label": "아이디", "type": "text", "value": "admin@gaon.co.kr", "required": True},
        {"label": "초기 비밀번호", "type": "secret", "value": "Gx8!pR2m#Vt7Lq4w", "required": True},
    ]

    def vm(name, ip):
        f = [
            {"label": "VM 이름", "value": name, "required": True},
            {"label": "접속 주소", "value": ip, "required": True},
            {"label": "SSH 포트", "value": "22"},
            {"label": "계정", "value": "root"},
        ]
        if key_files:
            f.append({"label": "키 파일", "type": "file", "required": True, "file_index": 0})
        return f

    d = {
        "template_id": None, "customer": "가온테크㈜", "title": "IXcloud 신규 계정 및 VM 생성 안내",
        "ticket": "REQ-1", "owner": "홍길동", "expiry": "24h", "policy": policy,
        "sections": [
            {"title": "IXcloud 콘솔 계정", "instances": [console], "notices": [{"tone": "warn", "text": "비밀번호를 변경해 주세요."}]},
            {"title": "VM 접속 정보", "repeat": True, "unit": "VM",
             "instances": [vm("web-01", "1.201.177.45"), vm("db-01", "1.201.177.46")],
             "notices": [{"tone": "info", "text": "콘솔(https://console.ixcloud.net)에서 보안그룹 SSH(22) 허용"}]},
        ],
    }
    d.update(over)
    return d


def create(admin, d=None, files=None):
    d = d or delivery()
    if files is None:
        files = [("files", ("gaon-key.pem", KEY, "application/octet-stream")),
                 ("files", ("extra.zip", b"PK\x03\x04zip", "application/zip"))]
    return admin.post("/api/secrets", data={"data": json.dumps(d)}, files=files, headers=H)


def token_of(r) -> str:
    return r.json()["link"].rsplit("/", 1)[1]


def row(secret_id):
    with db.connection() as conn:
        return conn.execute("SELECT * FROM secrets WHERE id = %s", (uuid.UUID(secret_id),)).fetchone()


def file_count(secret_id):
    with db.connection() as conn:
        return conn.execute("SELECT count(*) AS n FROM secret_files WHERE secret_id = %s", (uuid.UUID(secret_id),)).fetchone()["n"]


# ───────── 관리 ─────────
def test_state_changes_require_header(admin):
    r = admin.post("/api/secrets", data={"data": json.dumps(delivery())})
    assert r.status_code == 403


def test_create_stores_only_ciphertext(admin):
    r = create(admin)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["link"].startswith("https://seal.test/s/")
    assert "help_cloud@kinx.net" in body["mail"] and body["link"] in body["mail"]
    s = row(body["id"])
    raw = bytes(s["payload"])
    assert b"Gx8!pR2m" not in raw and "web-01".encode() not in raw
    assert s["token_hash"] != token_of(r).encode()
    assert s["file_count"] == 2 and s["section_count"] == 2
    with db.connection() as conn:
        blobs = [bytes(x["blob"]) for x in conn.execute("SELECT blob FROM secret_files")]
    assert all(b"OPENSSH" not in b for b in blobs)


def test_create_validation_errors(admin):
    d = delivery()
    d["sections"][1]["instances"][0][4]["file_index"] = None  # 필수 키 파일 누락
    r = create(admin, d)
    assert r.status_code == 400 and "키 파일" in r.json()["error"]

    r = create(admin, delivery(), files=[("files", ("evil.exe", b"MZ", "application/octet-stream"))])
    assert r.status_code == 400 and "올릴 수 없습니다" in r.json()["error"]

    r = create(admin, delivery(), files=[("files", ("renamed.pem", b"\x7fELF....", "application/octet-stream"))])
    assert r.status_code == 400

    r = create(admin, delivery(customer=""))
    assert r.status_code == 400 and "고객명" in r.json()["error"]


# ───────── 고객: 확인 후 폐기 ─────────
def test_until_confirmed_flow(admin, public):
    r = create(admin)
    sid, token = r.json()["id"], token_of(r)

    land = public.get(f"/s/{token}")
    assert land.status_code == 200
    assert "가온테크㈜" in land.text and "계정정보 보기" in land.text
    assert "Gx8!pR2m" not in land.text  # 안내 화면에는 내용이 없다
    assert land.headers["cache-control"] == "no-store"
    assert "default-src 'self'" in land.headers["content-security-policy"]
    assert land.headers["referrer-policy"] == "no-referrer"
    assert row(sid)["view_count"] == 0  # 링크 열기(메일 검사 등)는 열람이 아니다

    rv = public.post(f"/s/{token}/reveal")
    assert rv.status_code == 200
    t = rv.text
    for s in ("Gx8!pR2m#Vt7Lq4w", "VM 1 · web-01", "VM 2 · db-01", "gaon-key.pem", "extra.zip", "help_cloud@kinx.net", "확인 완료"):
        assert s in t, s
    assert '<a href="https://console.ixcloud.net"' in t
    assert row(sid)["view_count"] == 1

    # 파일: 세션 쿠키가 있어야 받을 수 있다
    import re

    fid = re.search(r"/s/%s/files/([0-9a-f-]{36})" % token, t).group(1)
    f = public.get(f"/s/{token}/files/{fid}")
    assert f.status_code == 200 and f.content in (KEY, b"PK\x03\x04zip")
    assert f.headers["content-disposition"].startswith("attachment;")
    assert f.headers["content-type"] == "application/octet-stream"
    assert "sandbox" in f.headers["content-security-policy"]

    from fastapi.testclient import TestClient

    stranger = TestClient(public.app, base_url="https://seal.test")
    assert stranger.get(f"/s/{token}/files/{fid}").status_code == 404
    assert stranger.post(f"/s/{token}/destroy").status_code == 404  # 세션 없이 폐기 불가

    # 여러 번 열람 가능
    assert public.post(f"/s/{token}/reveal").status_code == 200
    assert row(sid)["view_count"] == 2

    d = public.post(f"/s/{token}/destroy")
    assert d.status_code == 200 and "폐기했습니다" in d.text
    s = row(sid)
    assert s["status"] == "purged" and s["purge_reason"] == "customer_confirmed"
    assert s["payload"] is None and s["dek_wrapped"] is None and file_count(sid) == 0
    assert public.get(f"/s/{token}").status_code == 404
    assert public.post(f"/s/{token}/reveal").status_code == 404

    page = admin.get(f"/secrets/{sid}")
    assert page.status_code == 200
    for s in ("고객이 확인 후 폐기", "파일 받음", "열람", "링크 확인", "봉인"):
        assert s in page.text, s


# ───────── 고객: 1회 열람 ─────────
def test_one_time_with_files(admin, public, settings):
    r = create(admin, delivery("one_time"))
    sid, token = r.json()["id"], token_of(r)
    assert public.get(f"/s/{token}").status_code == 200  # 안내 화면은 소진하지 않는다
    assert row(sid)["status"] == "active"

    rv = public.post(f"/s/{token}/reveal")
    assert rv.status_code == 200 and "이미 폐기 처리되었습니다" in rv.text and "Gx8!pR2m#Vt7Lq4w" in rv.text
    s = row(sid)
    assert s["status"] == "consumed" and s["payload"] is None and file_count(sid) == 2

    assert public.post(f"/s/{token}/reveal").status_code == 404  # 두 번째 열람 불가
    import re

    fid = re.search(r"/files/([0-9a-f-]{36})", rv.text).group(1)
    assert public.get(f"/s/{token}/files/{fid}").status_code == 200  # 세션 동안은 파일 받기 가능

    with db.connection() as conn:
        conn.execute("UPDATE secrets SET consumed_at = now() - interval '1 hour' WHERE id = %s", (uuid.UUID(sid),))
        counts = service.run_maintenance(conn, session_minutes=settings.reveal_session_minutes, retention_days=730)
    assert counts["one_time"] == 1
    assert row(sid)["status"] == "purged" and file_count(sid) == 0


def test_one_time_without_files_purges_immediately(admin, public):
    r = create(admin, delivery("one_time", key_files=False), files=[])
    sid, token = r.json()["id"], token_of(r)
    rv = public.post(f"/s/{token}/reveal")
    assert rv.status_code == 200 and "Gx8!pR2m#Vt7Lq4w" in rv.text
    s = row(sid)
    assert s["status"] == "purged" and s["purge_reason"] == "one_time" and s["payload"] is None


# ───────── 만료 · 회수 · 재발급 ─────────
def test_expiry(admin, public, settings):
    r = create(admin)
    sid, token = r.json()["id"], token_of(r)
    with db.connection() as conn:
        conn.execute("UPDATE secrets SET expires_at = now() - interval '1 minute' WHERE id = %s", (uuid.UUID(sid),))
    assert public.get(f"/s/{token}").status_code == 404
    s = row(sid)
    assert s["status"] == "purged" and s["purge_reason"] == "expired" and file_count(sid) == 0

    r2 = create(admin)
    with db.connection() as conn:
        conn.execute("UPDATE secrets SET expires_at = now() - interval '1 minute' WHERE id = %s", (uuid.UUID(r2.json()["id"]),))
        counts = service.run_maintenance(conn, session_minutes=10, retention_days=730)
    assert counts["expired"] == 1


def test_reissue_and_revoke(admin, public):
    r = create(admin)
    sid, old = r.json()["id"], token_of(r)
    ri = admin.post(f"/api/secrets/{sid}/reissue", json={"owner": "김민서"}, headers=H)
    assert ri.status_code == 200
    new = ri.json()["link"].rsplit("/", 1)[1]
    assert new != old
    assert public.get(f"/s/{old}").status_code == 404
    assert public.get(f"/s/{new}").status_code == 200

    rv = admin.post(f"/api/secrets/{sid}/revoke", json={"owner": "김민서"}, headers=H)
    assert rv.status_code == 200
    assert public.get(f"/s/{new}").status_code == 404
    s = row(sid)
    assert s["purge_reason"] == "revoked" and s["payload"] is None
    assert admin.post(f"/api/secrets/{sid}/revoke", json={"owner": "x"}, headers=H).status_code == 400
    assert admin.post(f"/api/secrets/{sid}/reissue", json={"owner": "x"}, headers=H).status_code == 400


def test_invalid_tokens(public):
    for t in ("abc", "x" * 43, "../../etc/passwd"):
        assert public.get(f"/s/{t}").status_code == 404
    assert public.get("/s/" + "a" * 43 + "/files/not-a-uuid").status_code == 404


# ───────── 앱 분리 · 화면 ─────────
def test_public_app_has_no_admin_routes(public):
    for path in ("/secrets", "/templates", "/secrets/new"):
        r = public.get(path)
        assert r.status_code == 404 and "IXseal" in r.text
    assert public.post("/api/preview", json={}, headers=H).status_code in (404, 405)
    assert public.get("/healthz").json() == {"ok": True}


def test_admin_pages_render(admin):
    create(admin)
    for path in ("/secrets", "/secrets?status=wait&q=가온", "/secrets/new", "/templates", "/templates/new"):
        r = admin.get(path)
        assert r.status_code == 200, path
    lst = admin.get("/secrets").text
    assert "가온테크㈜" in lst and "대기" in lst
    new = admin.get("/secrets/new").text
    assert "신규 계정 + VM" in new and 'id="boot"' in new
    assert admin.get(f"/secrets/{uuid.uuid4()}").status_code == 404


# ───────── 템플릿 ─────────
def test_default_templates_use_key_files(admin):
    with db.connection() as conn:
        tpls = {t["name"]: t for t in service.list_templates(conn)}
    assert {"신규 계정 + VM", "VM 접속 정보", "IXcloud 콘솔 계정", "DB 계정", "빈 양식"} <= set(tpls)
    vm = tpls["신규 계정 + VM"]["sections"][1]
    types = {f["label"]: f["type"] for f in vm["fields"]}
    assert types["키 파일"] == "file" and "비밀번호" not in types
    assert any("보안그룹" in n["text"] for n in vm["notices"])


def test_template_crud(admin):
    body = {
        "name": "Windows VM", "description": "RDP", "default_title": "Windows VM 안내", "default_expiry": "3d",
        "default_policy": "unlimited", "updated_by": "홍길동",
        "sections": [{"title": "VM", "repeat": True, "unit": "VM", "fields": [{"label": "RDP 포트", "value": "3389"}],
                      "notices": [{"tone": "info", "text": "보안그룹에서 3389 허용"}]}],
    }
    r = admin.post("/api/templates", json=body, headers=H)
    assert r.status_code == 200
    tid = r.json()["id"]
    assert admin.get(f"/templates/{tid}/edit").status_code == 200

    body["name"] = "Windows VM (RDP)"
    assert admin.put(f"/api/templates/{tid}", json=body, headers=H).status_code == 200
    dup = admin.post(f"/api/templates/{tid}/duplicate", json={"owner": "홍길동"}, headers=H)
    assert dup.status_code == 200
    page = admin.get("/templates").text
    assert "Windows VM (RDP)" in page and "Windows VM (RDP) (복사본)" in page

    assert admin.post(f"/api/templates/{tid}/archive", json={"owner": "홍길동"}, headers=H).status_code == 200
    assert "Windows VM (RDP)</h3>" not in admin.get("/templates").text
    assert admin.get(f"/templates/{tid}/edit").status_code == 404

    bad = dict(body, sections=[{"title": "x", "fields": [{"label": "pw", "type": "secret", "value": "1234"}]}])
    r = admin.post("/api/templates", json=bad, headers=H)
    assert r.status_code == 400 and "기본값" in r.json()["error"]


def test_template_usage_counted(admin):
    with db.connection() as conn:
        t = service.list_templates(conn)[0]
    create(admin, delivery(template_id=str(t["id"])))
    with db.connection() as conn:
        assert service.get_template(conn, t["id"])["used_count"] == 1


# ───────── 미리보기 ─────────
def test_preview_renders_customer_markup(admin):
    body = {
        "view": "reveal", "mode": "tpl",
        "meta": {"customer": "고객사명", "title": "제목", "owner": "홍길동", "expiry": "24h", "policy": "until_confirmed"},
        "sections": [{"title": "VM 접속 정보", "repeat": True, "unit": "VM",
                      "instances": [[{"label": "VM 이름"}, {"label": "키 파일", "type": "file"}]],
                      "notices": [{"tone": "info", "text": "<b>x</b>"}]}],
    }
    r = admin.post("/api/preview", json=body, headers=H)
    assert r.status_code == 200
    assert "등록 시 입력" in r.text and "등록 시 첨부" in r.text
    assert "&lt;b&gt;x&lt;/b&gt;" in r.text  # 안내문 HTML은 이스케이프
    assert "/destroy" not in r.text  # 미리보기에는 실제 폐기 폼이 없다

    body.update(view="landing", mode="form")
    r = admin.post("/api/preview", json=body, headers=H)
    assert r.status_code == 200 and 'data-pv="reveal"' in r.text and "/reveal" not in r.text


@pytest.mark.parametrize("path", ["/", "/secrets"])
def test_admin_security_headers(admin, path):
    r = admin.get(path, follow_redirects=True)
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
