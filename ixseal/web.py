"""두 앱(고객·관리)이 함께 쓰는 웹 공통: 보안 헤더, 앱 수명주기, 응답 헬퍼."""

from __future__ import annotations

from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .config import Settings
from .crypto import KeyRing
from .render import STATIC_DIR, make_env

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
    "connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'"
)


def build_app(settings: Settings, keyring: KeyRing | None, *, title: str) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.keyring = keyring or KeyRing.load(settings.kek_file)  # 키가 없으면 여기서 바로 실패
        owned = db._pool is None
        db.open_pool(settings.database_url)
        yield
        if owned:
            db.close_pool()

    app = FastAPI(title=title, docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.settings = settings
    app.state.env = make_env(settings)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        h = resp.headers
        h.setdefault("Content-Security-Policy", CSP)
        h["X-Content-Type-Options"] = "nosniff"
        h["Referrer-Policy"] = "no-referrer"
        h["X-Frame-Options"] = "DENY"
        h["X-Robots-Tag"] = "noindex, nofollow"
        h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), interest-cohort=()"
        h["Cross-Origin-Opener-Policy"] = "same-origin"
        if not request.url.path.startswith("/static/"):
            h["Cache-Control"] = "no-store"
        return resp

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        with db.connection() as conn:
            conn.execute("SELECT 1")
        return {"ok": True}

    if settings.serve_static:
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def render(request: Request, name: str, status_code: int = 200, **ctx) -> HTMLResponse:
    html = request.app.state.env.get_template(name).render(**ctx)
    return HTMLResponse(html, status_code=status_code)


def client_ip(request: Request) -> str | None:
    # 운영: Nginx → uvicorn --proxy-headers 가 X-Forwarded-For를 반영한다
    return request.client.host if request.client else None


def user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")


def content_disposition(name: str) -> str:
    fallback = "".join(c if c.isascii() and c.isprintable() and c not in '"\\;' else "_" for c in name) or "file"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(name, safe='')}"
