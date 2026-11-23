"""Jinja 환경, 표시용 필터 (시간·크기·자동 링크)."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

from .files import human_size

BASE_DIR = Path(__file__).parent
TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

_URL = re.compile(r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$%+,;=]+")
_EMAIL = re.compile(r"(?<![A-Za-z0-9_.+\-/:@])([A-Za-z0-9_.+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+)")
_TRAIL = ".,;:!?"


def linkify(text: str) -> Markup:
    """일반 텍스트를 이스케이프한 뒤 http(s) URL과 메일 주소만 링크로 바꾼다. HTML 입력은 받지 않는다."""
    s = str(escape(text or ""))

    def url(m: re.Match) -> str:
        u, tail = m.group(0), ""
        while u and u[-1] in _TRAIL:
            u, tail = u[:-1], u[-1] + tail
        return f'<a href="{u}" target="_blank" rel="noopener noreferrer">{u}</a>{tail}'

    s = _URL.sub(url, s)
    s = _EMAIL.sub(lambda m: f'<a href="mailto:{m.group(1)}">{m.group(1)}</a>', s)
    return Markup(s.replace("\n", "<br>"))


def remaining_text(expires_at: datetime, now: datetime | None = None) -> str:
    """'23시간 12분', '3일 4시간'. 48시간 미만은 시간 단위."""
    now = now or datetime.now(timezone.utc)
    secs = int((expires_at - now).total_seconds())
    if secs <= 0:
        return "만료됨"
    mins = (secs + 59) // 60
    days = mins // 1440 if mins >= 2880 else 0
    hours = (mins - days * 1440) // 60
    m = mins % 60
    parts = [f"{days}일" if days else "", f"{hours}시간" if hours else "", f"{m}분" if m and not days else ""]
    return " ".join(p for p in parts if p) or "1분 미만"


class Clock:
    """표시용 시간대 변환."""

    def __init__(self, tz: str):
        self.tz = ZoneInfo(tz)

    def local(self, dt: datetime) -> datetime:
        return dt.astimezone(self.tz)

    def md_hm(self, dt: datetime | None) -> str:
        if dt is None:
            return "-"
        d = self.local(dt)
        return f"{d.month}월 {d.day}일 {d:%H:%M}"

    def full(self, dt: datetime | None) -> str:
        if dt is None:
            return "-"
        d = self.local(dt)
        return f"{d.year}년 {d.month}월 {d.day}일 {d:%H:%M}"

    def hm(self, dt: datetime) -> str:
        return f"{self.local(dt):%H:%M}"

    def relative(self, dt: datetime | None) -> str:
        """목록용: 오늘 14:30 / 어제 18:40 / 11월 20일"""
        if dt is None:
            return "-"
        d = self.local(dt)
        today = datetime.now(self.tz).date()
        delta = (today - d.date()).days
        if delta == 0:
            return f"오늘 {d:%H:%M}"
        if delta == 1:
            return f"어제 {d:%H:%M}"
        if d.year == today.year:
            return f"{d.month}월 {d.day}일"
        return f"{d.year}.{d.month}.{d.day}"


def actor_label(actor: str) -> str:
    if actor == "customer":
        return "고객"
    if actor == "system":
        return "시스템"
    return actor.removeprefix("admin:")


_BROWSERS = (("Edg/", "Edge"), ("Whale/", "Whale"), ("SamsungBrowser/", "Samsung"), ("Firefox/", "Firefox"),
             ("Chrome/", "Chrome"), ("Safari/", "Safari"))
_OSES = (("Windows", "Windows"), ("iPhone", "iOS"), ("iPad", "iPadOS"), ("Android", "Android"),
         ("Mac OS X", "macOS"), ("Linux", "Linux"))


def ua_short(ua: str | None) -> str:
    """기록 표시용 간단한 브라우저/OS 이름."""
    if not ua:
        return "알 수 없음"
    b = next((name for key, name in _BROWSERS if key in ua), None)
    o = next((name for key, name in _OSES if key in ua), None)
    if b and o:
        return f"{b} / {o}"
    return ua[:60]


@lru_cache
def asset_version() -> str:
    h = hashlib.sha1()
    for p in sorted(STATIC_DIR.glob("css/*.css")) + sorted(STATIC_DIR.glob("js/*.js")) + [STATIC_DIR / "img/icons.svg"]:
        if p.exists():
            h.update(p.read_bytes())
    return h.hexdigest()[:10]


def make_env(settings) -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    clock = Clock(settings.timezone)
    env.filters["linkify"] = linkify
    env.filters["size"] = human_size
    env.filters["md_hm"] = clock.md_hm
    env.filters["full"] = clock.full
    env.filters["hm"] = clock.hm
    env.filters["rel"] = clock.relative
    env.filters["remaining"] = remaining_text
    env.filters["actor"] = actor_label
    env.filters["ua_short"] = ua_short
    env.globals["settings"] = settings
    env.globals["v_asset"] = asset_version()
    env.globals["icon"] = lambda name, cls="": Markup(
        f'<svg class="icon {escape(cls)}" aria-hidden="true"><use href="/static/img/icons.svg?v={asset_version()}#{escape(name)}"/></svg>'
    )
    return env
