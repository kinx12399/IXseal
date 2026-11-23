"""핵심 로직: 등록, 열람, 파일 받기, 폐기, 회수, 재발급, 정리 작업, 관리 조회.

모든 함수는 호출자가 연 트랜잭션(conn) 안에서 동작한다.
"""

from __future__ import annotations

import ipaddress
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from psycopg.types.json import Jsonb

from . import crypto
from .crypto import KeyRing
from .files import sanitize_filename
from .schema import EXPIRY_HOURS, DeliveryIn, TemplateIn


class ServiceError(ValueError):
    """사용자에게 그대로 보여줄 수 있는 오류."""


# ───────── 공통 ─────────
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def clean_ip(ip: str | None) -> str | None:
    if not ip:
        return None
    try:
        return str(ipaddress.ip_address(ip))
    except ValueError:
        return None


_BOT = re.compile(
    r"bot|crawl|spider|preview|scan|safelinks|proofpoint|mimecast|barracuda|python|curl|wget|go-http|java/|okhttp|headless",
    re.I,
)


def is_automated(ua: str | None) -> bool:
    """메일 보안 검사·미리보기 같은 자동 접속 추정 (기록 표시용, 차단에는 쓰지 않는다)."""
    return not ua or "Mozilla" not in ua or bool(_BOT.search(ua))


def log(conn, event: str, actor: str, *, secret_id=None, template_id=None, detail: str = "", ip=None, ua=None) -> None:
    conn.execute(
        """INSERT INTO access_logs (secret_id, template_id, event, actor, detail, ip, user_agent)
           VALUES (%s, %s, %s, %s, %s, %s::inet, %s)""",
        (secret_id, template_id, event, actor[:60], detail[:500], clean_ip(ip), (ua or "")[:400] or None),
    )


def purge(conn, secret_id: uuid.UUID, reason: str) -> None:
    """내용·키·파일·세션을 지운다. 메타데이터는 감사용으로 남긴다."""
    conn.execute(
        """UPDATE secrets SET status = 'purged', purge_reason = %s, purged_at = now(),
                              payload = NULL, dek_wrapped = NULL, kek_id = NULL
           WHERE id = %s AND status <> 'purged'""",
        (reason, secret_id),
    )
    conn.execute("DELETE FROM secret_files WHERE secret_id = %s", (secret_id,))
    conn.execute("DELETE FROM reveal_sessions WHERE secret_id = %s", (secret_id,))


def _dek(keyring: KeyRing, row: dict) -> bytes:
    return keyring.unwrap(row["kek_id"], bytes(row["dek_wrapped"]), crypto.aad_dek(row["id"]))


def _payload(dek: bytes, row: dict) -> dict:
    return json.loads(crypto.unseal(dek, bytes(row["payload"]), crypto.aad_payload(row["id"])))


# ───────── 등록 ─────────
@dataclass
class Created:
    id: uuid.UUID
    token: str
    expires_at: datetime


def create_delivery(conn, keyring: KeyRing, data: DeliveryIn, uploads: list[tuple[str, bytes]], *, ip=None) -> Created:
    files_meta = [
        {"id": str(uuid.uuid4()), "name": sanitize_filename(name), "size": len(content)} for name, content in uploads
    ]
    sections: list[dict] = []
    field_count = 0
    for s in data.sections:
        instances = []
        for inst in s.instances:
            out = []
            for f in inst:
                label = f.label or "항목"
                if f.type == "file":
                    if f.file_index is None:
                        if f.required:
                            raise ServiceError(f"‘{label}’ 파일을 선택해 주세요")
                        out.append({"label": f.label, "type": "file", "value": ""})
                        continue
                    if f.file_index >= len(files_meta):
                        raise ServiceError("파일 정보가 올바르지 않습니다. 파일을 다시 선택해 주세요")
                    meta = files_meta[f.file_index]
                    out.append({"label": f.label, "type": "file", "value": meta["name"], "file_id": meta["id"]})
                    field_count += 1
                    continue
                value = f.value if f.type == "multi" else f.value.strip()
                if f.required and not value.strip():
                    raise ServiceError(f"‘{label}’ 항목을 입력해 주세요")
                out.append({"label": f.label, "type": f.type, "value": value})
                if value:
                    field_count += 1
            instances.append(out)
        sections.append(
            {
                "title": s.title,
                "repeat": s.repeat,
                "unit": s.unit,
                "instances": instances,
                "notices": [n.model_dump() for n in s.notices if n.text.strip()],
            }
        )
    if field_count == 0 and not uploads:
        raise ServiceError("전달할 내용이 없습니다")

    secret_id = uuid.uuid4()
    dek = crypto.new_dek()
    kek_id, dek_wrapped = keyring.wrap(dek, crypto.aad_dek(secret_id))
    payload = {"v": 1, "sections": sections, "files": files_meta}
    sealed = crypto.seal(dek, json.dumps(payload, ensure_ascii=False).encode("utf-8"), crypto.aad_payload(secret_id))
    token = crypto.new_token()

    template_id, template_name = None, ""
    if data.template_id:
        t = conn.execute(
            "UPDATE templates SET used_count = used_count + 1 WHERE id = %s RETURNING id, name", (data.template_id,)
        ).fetchone()
        if t:
            template_id, template_name = t["id"], t["name"]

    row = conn.execute(
        """INSERT INTO secrets (id, token_hash, title, customer_name, ticket_ref, owner_name, template_id, template_name,
                                policy, payload, dek_wrapped, kek_id, section_count, field_count, file_count,
                                created_ip, expires_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::inet,
                   now() + make_interval(hours => %s::int))
           RETURNING expires_at""",
        (
            secret_id, crypto.token_hash(token), data.title, data.customer, data.ticket, data.owner,
            template_id, template_name, data.policy, sealed, dek_wrapped, kek_id,
            len(sections), field_count, len(files_meta), clean_ip(ip), EXPIRY_HOURS[data.expiry],
        ),
    ).fetchone()
    for pos, ((_, content), meta) in enumerate(zip(uploads, files_meta)):
        fid = uuid.UUID(meta["id"])
        blob = crypto.seal(dek, crypto.pack_file(meta["name"], content), crypto.aad_file(secret_id, fid))
        conn.execute(
            "INSERT INTO secret_files (id, secret_id, position, size_bytes, blob) VALUES (%s, %s, %s, %s, %s)",
            (fid, secret_id, pos, len(content), blob),
        )
    log(conn, "created", f"admin:{data.owner}", secret_id=secret_id, detail=template_name, ip=ip)
    return Created(secret_id, token, row["expires_at"])


# ───────── 고객 ─────────
def find_by_token(conn, token: str, *, lock: bool = False) -> dict | None:
    if not crypto.looks_like_token(token):
        return None
    sql = "SELECT * FROM secrets WHERE token_hash = %s" + (" FOR UPDATE" if lock else "")
    return conn.execute(sql, (crypto.token_hash(token),)).fetchone()


def _expire_if_due(conn, row: dict) -> bool:
    """기한이 지났으면 폐기하고 True."""
    if row["status"] == "active" and row["expires_at"] <= utcnow():
        purge(conn, row["id"], "expired")
        log(conn, "expired", "system", secret_id=row["id"])
        return True
    return False


def landing(conn, token: str, *, ip=None, ua=None) -> dict | None:
    """안내 화면. 열람으로 세지 않는다 (메일 보안 검사가 링크를 미리 열어도 소진되지 않게)."""
    row = find_by_token(conn, token, lock=True)
    if row is None:
        log(conn, "invalid_token", "customer", ip=ip, ua=ua)
        return None
    if row["status"] != "active" or _expire_if_due(conn, row):
        return None
    log(conn, "landing", "customer", secret_id=row["id"], detail="auto" if is_automated(ua) else "", ip=ip, ua=ua)
    return row


@dataclass
class Revealed:
    row: dict
    payload: dict
    session: str | None


def reveal(conn, keyring: KeyRing, token: str, *, session_minutes: int, ip=None, ua=None) -> Revealed | None:
    row = find_by_token(conn, token, lock=True)
    if row is None:
        log(conn, "invalid_token", "customer", ip=ip, ua=ua)
        return None
    if row["status"] != "active" or _expire_if_due(conn, row):
        return None

    payload = _payload(_dek(keyring, row), row)
    has_files = row["file_count"] > 0
    conn.execute(
        """UPDATE secrets SET view_count = view_count + 1, last_viewed_at = now(),
                              first_viewed_at = coalesce(first_viewed_at, now())
           WHERE id = %s""",
        (row["id"],),
    )
    log(conn, "revealed", "customer", secret_id=row["id"], ip=ip, ua=ua)

    if row["policy"] == "one_time":
        if has_files:
            # 텍스트는 바로 지우고, 파일은 열람 세션 동안만 받을 수 있게 둔다 (정리 작업이 이후 폐기)
            conn.execute(
                "UPDATE secrets SET status = 'consumed', consumed_at = now(), payload = NULL WHERE id = %s", (row["id"],)
            )
        else:
            purge(conn, row["id"], "one_time")
            log(conn, "purged", "system", secret_id=row["id"], detail="one_time")

    session = None
    if has_files or row["policy"] == "until_confirmed":
        session = crypto.new_token()
        conn.execute(
            "INSERT INTO reveal_sessions (id_hash, secret_id, expires_at) VALUES (%s, %s, now() + make_interval(mins => %s::int))",
            (crypto.token_hash(session), row["id"], session_minutes),
        )
    return Revealed(row, payload, session)


def _session_ok(conn, secret_id: uuid.UUID, session: str | None) -> bool:
    if not session or not crypto.looks_like_token(session):
        return False
    return (
        conn.execute(
            "SELECT 1 FROM reveal_sessions WHERE id_hash = %s AND secret_id = %s AND expires_at > now()",
            (crypto.token_hash(session), secret_id),
        ).fetchone()
        is not None
    )


def download(conn, keyring: KeyRing, token: str, file_id: str, session: str | None, *, ip=None, ua=None) -> tuple[str, bytes] | None:
    row = find_by_token(conn, token)
    if row is None or row["status"] == "purged":
        return None
    if row["status"] == "active" and row["expires_at"] <= utcnow():
        return None
    if not _session_ok(conn, row["id"], session):
        return None
    try:
        fid = uuid.UUID(file_id)
    except ValueError:
        return None
    f = conn.execute("SELECT id, blob FROM secret_files WHERE id = %s AND secret_id = %s", (fid, row["id"])).fetchone()
    if f is None:
        return None
    plain = crypto.unseal(_dek(keyring, row), bytes(f["blob"]), crypto.aad_file(row["id"], f["id"]))
    name, data = crypto.unpack_file(plain)
    log(conn, "file_downloaded", "customer", secret_id=row["id"], detail=name, ip=ip, ua=ua)
    return name, data


def destroy(conn, token: str, session: str | None, *, ip=None, ua=None) -> bool:
    """고객이 [확인 완료 · 지금 폐기]를 눌렀을 때."""
    row = find_by_token(conn, token, lock=True)
    if row is None or row["status"] != "active" or row["policy"] != "until_confirmed":
        return False
    if not _session_ok(conn, row["id"], session):
        return False
    purge(conn, row["id"], "customer_confirmed")
    log(conn, "destroyed", "customer", secret_id=row["id"], ip=ip, ua=ua)
    return True


# ───────── 관리 ─────────
def revoke(conn, secret_id: uuid.UUID, owner: str, *, ip=None) -> bool:
    row = conn.execute("SELECT id, status FROM secrets WHERE id = %s FOR UPDATE", (secret_id,)).fetchone()
    if row is None or row["status"] == "purged":
        return False
    purge(conn, secret_id, "revoked")
    log(conn, "revoked", f"admin:{owner}", secret_id=secret_id, ip=ip)
    return True


def reissue(conn, secret_id: uuid.UUID, owner: str, *, ip=None) -> str | None:
    """새 링크를 만들고 기존 링크는 즉시 무효로 한다. 내용과 기한은 그대로."""
    row = conn.execute("SELECT * FROM secrets WHERE id = %s FOR UPDATE", (secret_id,)).fetchone()
    if row is None or row["status"] != "active" or _expire_if_due(conn, row):
        return None
    token = crypto.new_token()
    conn.execute("UPDATE secrets SET token_hash = %s WHERE id = %s", (crypto.token_hash(token), secret_id))
    conn.execute("DELETE FROM reveal_sessions WHERE secret_id = %s", (secret_id,))
    log(conn, "reissued", f"admin:{owner}", secret_id=secret_id, ip=ip)
    return token


def run_maintenance(conn, *, session_minutes: int, retention_days: int) -> dict[str, int]:
    """정리 작업 (5분마다): 만료 폐기, 1회 열람 후 남은 파일 폐기, 세션·오래된 기록 삭제."""
    counts = {"expired": 0, "one_time": 0}
    for r in conn.execute(
        "SELECT id FROM secrets WHERE status = 'active' AND expires_at <= now() FOR UPDATE SKIP LOCKED"
    ).fetchall():
        purge(conn, r["id"], "expired")
        log(conn, "expired", "system", secret_id=r["id"])
        counts["expired"] += 1
    for r in conn.execute(
        """SELECT id FROM secrets WHERE status = 'consumed'
             AND consumed_at <= now() - make_interval(mins => %s::int) FOR UPDATE SKIP LOCKED""",
        (session_minutes,),
    ).fetchall():
        purge(conn, r["id"], "one_time")
        log(conn, "purged", "system", secret_id=r["id"], detail="one_time")
        counts["one_time"] += 1
    counts["sessions"] = conn.execute("DELETE FROM reveal_sessions WHERE expires_at <= now()").rowcount
    counts["old_logs"] = conn.execute(
        "DELETE FROM access_logs WHERE at < now() - make_interval(days => %s::int)", (retention_days,)
    ).rowcount
    counts["old_secrets"] = conn.execute(
        "DELETE FROM secrets WHERE status = 'purged' AND created_at < now() - make_interval(days => %s::int)",
        (retention_days,),
    ).rowcount
    return counts


# ───────── 관리 조회 ─────────
UI_STATUS_SQL = """CASE
    WHEN s.status = 'active' AND s.expires_at <= now() THEN 'expired'
    WHEN s.status = 'active' AND s.view_count = 0 THEN 'wait'
    WHEN s.status = 'active' THEN 'viewed'
    WHEN s.status = 'consumed' THEN 'destroyed'
    WHEN s.purge_reason = 'expired' THEN 'expired'
    WHEN s.purge_reason = 'revoked' THEN 'revoked'
    ELSE 'destroyed' END"""

UI_STATUSES = ("wait", "viewed", "destroyed", "expired", "revoked")

_LIST_COLS = """s.id, s.title, s.customer_name, s.ticket_ref, s.owner_name, s.template_name, s.policy, s.status,
    s.purge_reason, s.created_at, s.expires_at, s.view_count, s.first_viewed_at, s.purged_at,
    s.section_count, s.field_count, s.file_count"""


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def list_secrets(conn, *, status: str | None, q: str, limit: int, offset: int) -> tuple[list[dict], dict[str, int]]:
    where, params = "", []
    if q:
        where = """WHERE (s.title ILIKE %s OR s.customer_name ILIKE %s OR s.owner_name ILIKE %s
                          OR s.ticket_ref ILIKE %s OR s.template_name ILIKE %s)"""
        params = [_like(q)] * 5
    base = f"SELECT {_LIST_COLS}, {UI_STATUS_SQL} AS ui_status FROM secrets s {where}"
    counts = {r["ui_status"]: r["n"] for r in conn.execute(f"SELECT ui_status, count(*) AS n FROM ({base}) x GROUP BY ui_status", params)}
    counts["all"] = sum(counts.values())
    sql = f"SELECT * FROM ({base}) x"
    p2 = list(params)
    if status in UI_STATUSES:
        sql += " WHERE ui_status = %s"
        p2.append(status)
    sql += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
    p2 += [limit, offset]
    return conn.execute(sql, p2).fetchall(), counts


def stats(conn, tz: str) -> dict[str, int]:
    return conn.execute(
        """WITH t AS (SELECT (date_trunc('day', now() AT TIME ZONE %s) AT TIME ZONE %s) AS today)
           SELECT
             count(*) FILTER (WHERE status = 'active' AND expires_at > now() AND view_count = 0) AS waiting,
             count(*) FILTER (WHERE first_viewed_at >= t.today) AS viewed_today,
             count(*) FILTER (WHERE created_at >= t.today) AS created_today,
             count(*) FILTER (WHERE status = 'active' AND expires_at > now()
                                AND expires_at <= now() + interval '6 hours') AS expiring
           FROM secrets, t""",
        (tz, tz),
    ).fetchone()


def get_secret(conn, secret_id: uuid.UUID) -> dict | None:
    return conn.execute(
        f"SELECT {_LIST_COLS}, s.last_viewed_at, s.consumed_at, {UI_STATUS_SQL} AS ui_status FROM secrets s WHERE s.id = %s",
        (secret_id,),
    ).fetchone()


def secret_logs(conn, secret_id: uuid.UUID) -> list[dict]:
    return conn.execute(
        "SELECT event, actor, detail, host(ip) AS ip, user_agent, at FROM access_logs WHERE secret_id = %s ORDER BY at DESC, id DESC LIMIT 200",
        (secret_id,),
    ).fetchall()


# ───────── 템플릿 ─────────
def list_templates(conn) -> list[dict]:
    return conn.execute(
        "SELECT * FROM templates WHERE archived_at IS NULL ORDER BY sort_order, created_at"
    ).fetchall()


def get_template(conn, template_id: uuid.UUID) -> dict | None:
    return conn.execute("SELECT * FROM templates WHERE id = %s AND archived_at IS NULL", (template_id,)).fetchone()


def save_template(conn, data: TemplateIn, template_id: uuid.UUID | None = None, *, ip=None) -> uuid.UUID:
    sections: list[dict[str, Any]] = [s.model_dump() for s in data.sections]
    if template_id is None:
        template_id = uuid.uuid4()
        order = conn.execute("SELECT coalesce(max(sort_order), 0) + 10 AS o FROM templates").fetchone()["o"]
        conn.execute(
            """INSERT INTO templates (id, name, description, default_title, default_expiry, default_policy,
                                      sections, sort_order, updated_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (template_id, data.name, data.description, data.default_title, data.default_expiry,
             data.default_policy, Jsonb(sections), order, data.updated_by),
        )
    else:
        cur = conn.execute(
            """UPDATE templates SET name = %s, description = %s, default_title = %s, default_expiry = %s,
                                    default_policy = %s, sections = %s, updated_by = %s, updated_at = now()
               WHERE id = %s AND archived_at IS NULL""",
            (data.name, data.description, data.default_title, data.default_expiry, data.default_policy,
             Jsonb(sections), data.updated_by, template_id),
        )
        if cur.rowcount == 0:
            raise ServiceError("템플릿을 찾을 수 없습니다")
    log(conn, "template_saved", f"admin:{data.updated_by}", template_id=template_id, detail=data.name, ip=ip)
    return template_id


def duplicate_template(conn, template_id: uuid.UUID, owner: str, *, ip=None) -> uuid.UUID:
    t = get_template(conn, template_id)
    if t is None:
        raise ServiceError("템플릿을 찾을 수 없습니다")
    new_id = uuid.uuid4()
    conn.execute(
        "UPDATE templates SET sort_order = sort_order + 1 WHERE sort_order > %s", (t["sort_order"],)
    )
    conn.execute(
        """INSERT INTO templates (id, name, description, default_title, default_expiry, default_policy,
                                  sections, sort_order, updated_by)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (new_id, (t["name"] + " (복사본)")[:60], t["description"], t["default_title"], t["default_expiry"],
         t["default_policy"], Jsonb(t["sections"]), t["sort_order"] + 1, owner),
    )
    log(conn, "template_saved", f"admin:{owner}", template_id=new_id, detail=f"복제: {t['name']}", ip=ip)
    return new_id


def archive_template(conn, template_id: uuid.UUID, owner: str, *, ip=None) -> bool:
    cur = conn.execute(
        "UPDATE templates SET archived_at = now(), updated_by = %s WHERE id = %s AND archived_at IS NULL",
        (owner, template_id),
    )
    if cur.rowcount:
        log(conn, "template_archived", f"admin:{owner}", template_id=template_id, ip=ip)
    return bool(cur.rowcount)
