"""기본 템플릿. 템플릿이 하나도 없을 때만 넣는다 (이후에는 관리 화면에서 자유롭게 고친다)."""

from __future__ import annotations

import uuid

from psycopg.types.json import Jsonb


def _f(label: str, type_: str = "text", value: str = "", required: bool = True) -> dict:
    return {"label": label, "type": type_, "value": value, "required": required}


CONSOLE_URL = "https://console.ixcloud.net"
PW_NOTICE = {"tone": "warn", "text": "처음 로그인한 뒤 비밀번호를 변경해 주세요."}
KEY_NOTICE = {
    "tone": "warn",
    "text": "VM은 비밀번호가 아니라 키 파일로 접속합니다. 키 파일은 다시 받기 어려우니 안전한 곳에 보관해 주세요.\n"
    "Linux·macOS: chmod 600 <키 파일> 로 권한을 바꾼 뒤 ssh -i <키 파일> -p <SSH 포트> <계정>@<접속 주소>",
}
SG_NOTICE_WITH_ACCOUNT = {
    "tone": "info",
    "text": f"VM에 접속하려면 먼저 위 콘솔 계정으로 IXcloud 콘솔({CONSOLE_URL})에 로그인한 뒤, "
    "해당 VM의 보안그룹에서 접속하실 곳의 IP에 SSH(22) 포트를 허용해 주세요.",
}
SG_NOTICE = {
    "tone": "info",
    "text": f"VM에 접속하려면 먼저 IXcloud 콘솔({CONSOLE_URL})에 로그인한 뒤, "
    "해당 VM의 보안그룹에서 접속하실 곳의 IP에 SSH(22) 포트를 허용해 주세요.",
}


def console_section() -> dict:
    return {
        "title": "IXcloud 콘솔 계정",
        "repeat": False,
        "unit": "",
        "fields": [_f("콘솔 주소", "url", CONSOLE_URL), _f("아이디"), _f("초기 비밀번호", "secret")],
        "notices": [PW_NOTICE],
    }


def vm_section(sg_notice: dict) -> dict:
    return {
        "title": "VM 접속 정보",
        "repeat": True,
        "unit": "VM",
        "fields": [
            _f("VM 이름"),
            _f("접속 주소"),
            _f("SSH 포트", "text", "22"),
            _f("계정", "text", "root"),
            _f("키 파일", "file"),
        ],
        "notices": [sg_notice, KEY_NOTICE],
    }


DEFAULT_TEMPLATES: list[dict] = [
    {
        "name": "신규 계정 + VM",
        "description": "신규 고객에게 IXcloud 콘솔 계정과 VM 접속 정보(키 파일)를 함께 전달합니다.",
        "default_title": "IXcloud 신규 계정 및 VM 생성 안내",
        "default_expiry": "24h",
        "default_policy": "until_confirmed",
        "sections": [console_section(), vm_section(SG_NOTICE_WITH_ACCOUNT)],
    },
    {
        "name": "VM 접속 정보",
        "description": "기존 고객에게 새로 만든 VM의 접속 정보와 키 파일을 전달합니다.",
        "default_title": "VM 생성 완료 안내",
        "default_expiry": "24h",
        "default_policy": "until_confirmed",
        "sections": [vm_section(SG_NOTICE)],
    },
    {
        "name": "IXcloud 콘솔 계정",
        "description": "콘솔 추가 사용자·서브계정을 발급할 때 사용합니다.",
        "default_title": "IXcloud 콘솔 계정 발급 안내",
        "default_expiry": "24h",
        "default_policy": "until_confirmed",
        "sections": [console_section()],
    },
    {
        "name": "DB 계정",
        "description": "관리형 DB 또는 VM 내 DB 계정을 전달합니다.",
        "default_title": "DB 계정 발급 안내",
        "default_expiry": "6h",
        "default_policy": "one_time",
        "sections": [
            {
                "title": "DB 접속 정보",
                "repeat": False,
                "unit": "",
                "fields": [_f("호스트"), _f("포트", "text", "3306"), _f("DB 이름", required=False), _f("계정"), _f("비밀번호", "secret")],
                "notices": [PW_NOTICE],
            }
        ],
    },
    {
        "name": "빈 양식",
        "description": "항목을 직접 채워 자유롭게 보냅니다.",
        "default_title": "",
        "default_expiry": "24h",
        "default_policy": "unlimited",
        "sections": [{"title": "계정 정보", "repeat": False, "unit": "", "fields": [_f("", required=False)], "notices": []}],
    },
]


def seed_templates(conn) -> int:
    if conn.execute("SELECT 1 FROM templates LIMIT 1").fetchone():
        return 0
    for i, t in enumerate(DEFAULT_TEMPLATES):
        conn.execute(
            """INSERT INTO templates (id, name, description, default_title, default_expiry, default_policy,
                                      sections, sort_order, updated_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'system')""",
            (uuid.uuid4(), t["name"], t["description"], t["default_title"], t["default_expiry"],
             t["default_policy"], Jsonb(t["sections"]), i * 10),
        )
    return len(DEFAULT_TEMPLATES)
