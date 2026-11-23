"""관리용 앱 (8443, 보안그룹으로 사무실 IP만 허용). 로그인 없음 — 담당자 이름은 브라우저에 기억해 함께 보낸다.

실행: uvicorn ixseal.admin_app:app --host 127.0.0.1 --port 8002 --proxy-headers --forwarded-allow-ips 127.0.0.1
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import ValidationError

from . import db, service
from .config import Settings, get_settings
from .crypto import KeyRing
from .files import UploadError, check_files
from .render import Clock, remaining_text
from .schema import (
    EXPIRY_LABEL,
    POLICY_LABEL,
    TYPE_LABEL,
    DeliveryIn,
    OwnerIn,
    PreviewIn,
    TemplateIn,
)
from .views import mail_text, preview_view
from .web import build_app, client_ip, render

PAGE_SIZE = 50

STATUS_TABS = [("all", "전체"), ("wait", "대기"), ("viewed", "열람됨"), ("destroyed", "폐기됨"), ("expired", "만료"), ("revoked", "회수")]
STATUS_LABEL = dict(STATUS_TABS)

FIELD_NAMES = {
    "customer": "고객명", "title": "제목", "owner": "담당자", "name": "템플릿 이름", "updated_by": "담당자",
    "label": "항목 이름", "value": "값", "text": "안내문", "sections": "섹션", "instances": "묶음", "fields": "항목",
    "ticket": "요청 번호", "unit": "단위", "description": "설명", "default_title": "기본 제목",
}

EVENT_LABEL = {
    "created": "봉인",
    "landing": "링크 확인 (열람 아님)",
    "revealed": "열람",
    "file_downloaded": "파일 받음",
    "destroyed": "고객이 확인 후 폐기",
    "revoked": "회수",
    "reissued": "링크 재발급",
    "expired": "기한 만료로 폐기",
    "purged": "1회 열람 후 폐기",
}


def _validation_message(errors: list[dict]) -> str:
    if not errors:
        return "입력값을 확인해 주세요"
    e = errors[0]
    names = [FIELD_NAMES.get(str(p)) for p in e.get("loc", ()) if FIELD_NAMES.get(str(p))]
    where = f" ({names[-1]})" if names else ""
    msg = e.get("msg", "")
    if msg.startswith("Value error, "):
        return msg.removeprefix("Value error, ")
    if "at least 1 character" in msg or e.get("type") == "missing":
        return f"필수 항목을 입력해 주세요{where}"
    if "at most" in msg:
        return f"입력값이 너무 깁니다{where}"
    return f"입력값을 확인해 주세요{where}"


def _err(msg: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": msg}, status_code=status)


def _boot_json(data: dict) -> str:
    """<script type="application/json"> 안에 넣을 JSON. </script> 등으로 깨지지 않게 꺾쇠·앰퍼샌드를 이스케이프한다."""
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


REASON_TEXT = {"one_time": "1회 열람으로 폐기", "customer_confirmed": "고객이 확인 후 폐기", "expired": "기한 만료", "revoked": "회수"}


def _decorate_row(r: dict, now: datetime) -> dict:
    """목록 표시용: 남은 시간, 진행 막대 비율, 폐기 사유."""
    r["remaining"] = remaining_text(r["expires_at"], now)
    total = (r["expires_at"] - r["created_at"]).total_seconds() or 1
    left = max((r["expires_at"] - now).total_seconds(), 0)
    r["pct"] = round(left / total * 100)
    r["soon"] = left < 6 * 3600
    if r["status"] == "consumed":
        r["reason"] = "1회 열람으로 폐기"
    else:
        r["reason"] = REASON_TEXT.get(r["purge_reason"] or "expired", "")
    return r


def _template_json(t: dict) -> dict:
    return {
        "id": str(t["id"]),
        "name": t["name"],
        "description": t["description"],
        "default_title": t["default_title"],
        "default_expiry": t["default_expiry"],
        "default_policy": t["default_policy"],
        "sections": t["sections"],
    }


def create_app(settings: Settings | None = None, keyring: KeyRing | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = build_app(settings, keyring, title="IXseal 관리")
    clock = Clock(settings.timezone)

    def link_for(token: str) -> str:
        return f"{settings.public_base_url.rstrip('/')}/s/{token}"

    def page(request: Request, name: str, active: str, status_code: int = 200, **ctx):
        return render(
            request, f"admin/{name}", status_code=status_code, active=active,
            EXPIRY_LABEL=EXPIRY_LABEL, POLICY_LABEL=POLICY_LABEL, TYPE_LABEL=TYPE_LABEL,
            STATUS_LABEL=STATUS_LABEL, EVENT_LABEL=EVENT_LABEL, **ctx,
        )

    # CSRF 방어: 상태를 바꾸는 요청은 커스텀 헤더가 있어야 한다 (다른 사이트의 폼·스크립트는 이 헤더를 붙여 보낼 수 없다)
    @app.middleware("http")
    async def require_header(request: Request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-ixseal") != "1":
            return _err("잘못된 요청입니다", 403)
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def validation(request: Request, exc: RequestValidationError):
        return _err(_validation_message(exc.errors()))

    # ───────── 화면 ─────────
    @app.get("/")
    def home():
        return RedirectResponse("/secrets", status_code=302)

    @app.get("/secrets", response_class=HTMLResponse)
    def secrets_list(request: Request, status: str = "all", q: str = "", page_no: int = 1):
        page_no = max(page_no, 1)
        q = q.strip()[:80]
        with db.connection() as conn:
            rows, counts = service.list_secrets(
                conn, status=None if status == "all" else status, q=q, limit=PAGE_SIZE, offset=(page_no - 1) * PAGE_SIZE
            )
            st = service.stats(conn, settings.timezone)
        total = counts.get(status, 0) if status != "all" else counts.get("all", 0)
        now = service.utcnow()
        rows = [_decorate_row(dict(r), now) for r in rows]
        return page(
            request, "secrets.html", "list", rows=rows, counts=counts, stats=st, status=status, q=q,
            page_no=page_no, has_next=page_no * PAGE_SIZE < total, tabs=STATUS_TABS, clock=clock,
        )

    @app.get("/secrets/new", response_class=HTMLResponse)
    def secrets_new(request: Request, template: str = ""):
        with db.connection() as conn:
            templates = [_template_json(t) for t in service.list_templates(conn)]
        boot = {
            "templates": templates,
            "selected": template,
            "limits": {"maxFileMb": settings.max_file_mb, "maxFiles": settings.max_files, "maxTotalMb": settings.max_total_mb},
        }
        return page(request, "new.html", "new", boot=_boot_json(boot))

    @app.get("/secrets/{secret_id}", response_class=HTMLResponse)
    def secret_detail(request: Request, secret_id: uuid.UUID):
        with db.connection() as conn:
            s = service.get_secret(conn, secret_id)
            logs = service.secret_logs(conn, secret_id) if s else []
        if s is None:
            return page(request, "notfound.html", "list", status_code=404)
        logs = [l for l in logs if l["event"] != "invalid_token"]
        return page(request, "detail.html", "list", s=s, logs=logs, clock=clock)

    @app.get("/templates", response_class=HTMLResponse)
    def templates_list(request: Request):
        with db.connection() as conn:
            rows = service.list_templates(conn)
        return page(request, "templates.html", "tpl", rows=rows, clock=clock)

    @app.get("/templates/new", response_class=HTMLResponse)
    def template_new(request: Request):
        return page(request, "template_edit.html", "tpl", boot=_boot_json({"template": None}))

    @app.get("/templates/{template_id}/edit", response_class=HTMLResponse)
    def template_edit(request: Request, template_id: uuid.UUID):
        with db.connection() as conn:
            t = service.get_template(conn, template_id)
        if t is None:
            return page(request, "notfound.html", "tpl", status_code=404)
        return page(request, "template_edit.html", "tpl", boot=_boot_json({"template": _template_json(t)}))

    # ───────── API ─────────
    @app.post("/api/secrets")
    def api_create(request: Request, data: str = Form(...), files: list[UploadFile] = File(default=[])):
        try:
            d = DeliveryIn.model_validate_json(data)
        except ValidationError as exc:
            return _err(_validation_message(exc.errors()))
        max_file = settings.max_file_mb * 1024 * 1024
        uploads = [(f.filename or "file", f.file.read(max_file + 1)) for f in files]
        try:
            check_files(uploads, max_files=settings.max_files, max_file_bytes=max_file,
                        max_total_bytes=settings.max_total_mb * 1024 * 1024)
            with db.connection() as conn:
                c = service.create_delivery(conn, request.app.state.keyring, d, uploads, ip=client_ip(request))
        except (UploadError, service.ServiceError) as exc:
            return _err(str(exc))
        link = link_for(c.token)
        return {
            "id": str(c.id),
            "link": link,
            "deadline": clock.md_hm(c.expires_at),
            "mail": mail_text(customer=d.customer, owner=d.owner, title=d.title, link=link,
                              deadline=clock.full(c.expires_at), policy=d.policy, helpdesk=settings.helpdesk_email),
        }

    @app.post("/api/secrets/{secret_id}/revoke")
    def api_revoke(request: Request, secret_id: uuid.UUID, body: OwnerIn):
        with db.connection() as conn:
            ok = service.revoke(conn, secret_id, body.owner, ip=client_ip(request))
        return {"ok": True} if ok else _err("이미 폐기되었거나 찾을 수 없습니다")

    @app.post("/api/secrets/{secret_id}/reissue")
    def api_reissue(request: Request, secret_id: uuid.UUID, body: OwnerIn):
        with db.connection() as conn:
            token = service.reissue(conn, secret_id, body.owner, ip=client_ip(request))
            s = service.get_secret(conn, secret_id) if token else None
        if not token or s is None:
            return _err("열람 가능한 상태에서만 재발급할 수 있습니다")
        link = link_for(token)
        return {
            "link": link,
            "mail": mail_text(customer=s["customer_name"], owner=body.owner, title=s["title"], link=link,
                              deadline=clock.full(s["expires_at"]), policy=s["policy"], helpdesk=settings.helpdesk_email),
        }

    @app.post("/api/templates")
    def api_template_create(request: Request, body: TemplateIn):
        with db.connection() as conn:
            tid = service.save_template(conn, body, ip=client_ip(request))
        return {"id": str(tid)}

    @app.put("/api/templates/{template_id}")
    def api_template_update(request: Request, template_id: uuid.UUID, body: TemplateIn):
        try:
            with db.connection() as conn:
                service.save_template(conn, body, template_id, ip=client_ip(request))
        except service.ServiceError as exc:
            return _err(str(exc), 404)
        return {"id": str(template_id)}

    @app.post("/api/templates/{template_id}/duplicate")
    def api_template_dup(request: Request, template_id: uuid.UUID, body: OwnerIn):
        try:
            with db.connection() as conn:
                tid = service.duplicate_template(conn, template_id, body.owner, ip=client_ip(request))
        except service.ServiceError as exc:
            return _err(str(exc), 404)
        return {"id": str(tid)}

    @app.post("/api/templates/{template_id}/archive")
    def api_template_archive(request: Request, template_id: uuid.UUID, body: OwnerIn):
        with db.connection() as conn:
            ok = service.archive_template(conn, template_id, body.owner, ip=client_ip(request))
        return {"ok": True} if ok else _err("템플릿을 찾을 수 없습니다", 404)

    @app.post("/api/preview", response_class=HTMLResponse)
    def api_preview(request: Request, body: PreviewIn):
        """입력 중인 내용을 실제 고객 화면과 같은 템플릿으로 그린다. 저장·기록하지 않는다."""
        return render(request, "customer/preview.html", v=preview_view(body), view=body.view)

    return app


def __getattr__(name: str):
    """`uvicorn ixseal.admin_app:app` 으로 불릴 때 앱을 만든다."""
    if name == "app":
        return create_app()
    raise AttributeError(name)
