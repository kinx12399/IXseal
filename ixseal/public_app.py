"""고객용 앱 (443, 전체 공개). 관리 기능은 이 앱에 아예 없다.

실행: uvicorn ixseal.public_app:app --host 127.0.0.1 --port 8001 --proxy-headers --forwarded-allow-ips 127.0.0.1
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import db, service
from .config import Settings, get_settings
from .crypto import KeyRing
from .views import real_view
from .web import build_app, client_ip, content_disposition, render, user_agent

COOKIE = "ixseal_rs"


def create_app(settings: Settings | None = None, keyring: KeyRing | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = build_app(settings, keyring, title="IXseal")

    def gone(request: Request, kind: str = "gone", status_code: int = 404):
        return render(request, "customer/gone.html", status_code=status_code, kind=kind)

    @app.exception_handler(StarletteHTTPException)
    async def not_found(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 405:
            return gone(request, "notfound", 405)
        return gone(request, "notfound", exc.status_code if exc.status_code >= 400 else 404)

    @app.get("/s/{token}")
    def landing(token: str, request: Request):
        with db.connection() as conn:
            row = service.landing(conn, token, ip=client_ip(request), ua=user_agent(request))
        if row is None:
            return gone(request)
        return render(request, "customer/landing.html", v=real_view(row, None), token=token)

    @app.get("/s/{token}/reveal")
    def reveal_get(token: str):
        return RedirectResponse(f"/s/{token}", status_code=303) if len(token) == 43 else RedirectResponse("/", 303)

    @app.post("/s/{token}/reveal")
    def reveal(token: str, request: Request):
        with db.connection() as conn:
            r = service.reveal(
                conn, request.app.state.keyring, token,
                session_minutes=settings.reveal_session_minutes, ip=client_ip(request), ua=user_agent(request),
            )
        if r is None:
            return gone(request)
        resp = render(
            request, "customer/reveal.html",
            v=real_view(r.row, r.payload), token=token,
            once=r.row["policy"] == "one_time", has_session=r.session is not None,
            session_minutes=settings.reveal_session_minutes,
        )
        if r.session:
            resp.set_cookie(
                COOKIE, r.session, max_age=settings.reveal_session_minutes * 60, path=f"/s/{token}",
                secure=settings.cookie_secure, httponly=True, samesite="strict",
            )
        return resp

    @app.get("/s/{token}/files/{file_id}")
    def download(token: str, file_id: str, request: Request):
        with db.connection() as conn:
            res = service.download(
                conn, request.app.state.keyring, token, file_id, request.cookies.get(COOKIE),
                ip=client_ip(request), ua=user_agent(request),
            )
        if res is None:
            return gone(request, "file")
        name, data = res
        return Response(
            content=data,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": content_disposition(name),
                "Content-Security-Policy": "sandbox; default-src 'none'",
            },
        )

    @app.post("/s/{token}/destroy")
    def destroy(token: str, request: Request):
        with db.connection() as conn:
            ok = service.destroy(conn, token, request.cookies.get(COOKIE), ip=client_ip(request), ua=user_agent(request))
        resp = gone(request, "destroyed" if ok else "gone", 200 if ok else 404)
        resp.delete_cookie(COOKIE, path=f"/s/{token}")
        return resp

    return app


def __getattr__(name: str):
    """`uvicorn ixseal.public_app:app` 으로 불릴 때 앱을 만든다 (테스트에서 import만 할 때는 만들지 않는다)."""
    if name == "app":
        return create_app()
    raise AttributeError(name)
