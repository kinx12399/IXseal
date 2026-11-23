"""DB 없이 도는 단위 테스트."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from ixseal import crypto, files
from ixseal.render import linkify, remaining_text, ua_short
from ixseal.schema import DeliveryIn, PreviewIn, TemplateIn
from ixseal.views import build_sections, mail_text, preview_view


# ───────── 암호화 ─────────
def test_keyring_wrap_and_aad(tmp_path):
    p = tmp_path / "kek"
    p.write_text("# c\n" + crypto.new_kek_line(1) + "\n" + crypto.new_kek_line(2) + "\n")
    ring = crypto.KeyRing.load(p)
    assert ring.current_id == 2
    sid = uuid.uuid4()
    kid, blob = ring.wrap(b"d" * 32, crypto.aad_dek(sid))
    assert ring.unwrap(kid, blob, crypto.aad_dek(sid)) == b"d" * 32
    with pytest.raises(crypto.CryptoError):
        ring.unwrap(kid, blob, crypto.aad_dek(uuid.uuid4()))  # 다른 행으로 옮긴 암호문


def test_cli_kek_files_roundtrip(tmp_path):
    from ixseal.__main__ import main

    p = tmp_path / "kek"
    assert main(["init-kek", str(p)]) == 0
    assert main(["init-kek", str(p)]) == 1  # 덮어쓰지 않는다
    assert crypto.KeyRing.load(p).current_id == 1  # 한글 주석이 있어도 읽힌다
    assert main(["rotate-kek", str(p)]) == 0
    assert crypto.KeyRing.load(p).current_id == 2


def test_seal_tamper_detected():
    key = crypto.new_dek()
    blob = bytearray(crypto.seal(key, b"secret", b"aad"))
    blob[-1] ^= 1
    with pytest.raises(crypto.CryptoError):
        crypto.unseal(key, bytes(blob), b"aad")


def test_token_and_file_pack():
    t = crypto.new_token()
    assert crypto.looks_like_token(t) and len(t) == 43
    assert not crypto.looks_like_token("../" + t[3:])
    assert crypto.unpack_file(crypto.pack_file("키 파일.pem", b"\x00abc")) == ("키 파일.pem", b"\x00abc")


# ───────── 파일 검사 ─────────
@pytest.mark.parametrize(
    "name,data",
    [("a.exe", b"x"), ("A.PS1", b"x"), ("renamed.txt", b"MZ\x90\x00"), ("elf.pem", b"\x7fELFxx"), ("s.key", b"#!/bin/bash"), ("e.txt", b"")],
)
def test_blocked_files(name, data):
    with pytest.raises(files.UploadError):
        files.check_file(name, data, 1024)


@pytest.mark.parametrize("name", ["web-01.pem", "id_rsa", "cert.key", "vpn.zip", "kube.yaml", "a.ppk", "readme.txt"])
def test_allowed_files(name):
    files.check_file(name, b"-----BEGIN OPENSSH PRIVATE KEY-----", 1024)


def test_file_limits():
    with pytest.raises(files.UploadError):
        files.check_file("big.zip", b"x" * 11, 10)
    with pytest.raises(files.UploadError):
        files.check_files([("a", b"x")] * 3, max_files=2, max_file_bytes=10, max_total_bytes=100)
    with pytest.raises(files.UploadError):
        files.check_files([("a", b"x" * 8), ("b", b"x" * 8)], max_files=5, max_file_bytes=10, max_total_bytes=10)


def test_sanitize_filename():
    assert files.sanitize_filename("../../etc/passwd") == "passwd"
    assert files.sanitize_filename("C:\\Users\\me\\key.pem") == "key.pem"
    assert files.sanitize_filename("a\x00b\n.pem") == "ab.pem"
    assert files.sanitize_filename("...") == "file"
    long = files.sanitize_filename("가" * 300 + ".pem")
    assert long.endswith(".pem") and len(long.encode()) <= 200


# ───────── 표시 ─────────
def test_linkify_escapes_and_links():
    html = str(linkify('<img src=x onerror=alert(1)> 콘솔(https://console.ixcloud.net)에서. help_cloud@kinx.net으로\n다음'))
    assert "<img" not in html and "&lt;img" in html
    assert '<a href="https://console.ixcloud.net" target="_blank" rel="noopener noreferrer">' in html
    assert '<a href="mailto:help_cloud@kinx.net">help_cloud@kinx.net</a>으로' in html
    assert "<br>" in html
    assert "javascript:" not in str(linkify("javascript:alert(1)")).replace("javascript:alert(1)", "")


def test_remaining_text():
    n = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert remaining_text(n + timedelta(hours=24), n) == "24시간"
    assert remaining_text(n + timedelta(hours=23, minutes=12), n) == "23시간 12분"
    assert remaining_text(n + timedelta(hours=68), n) == "2일 20시간"
    assert remaining_text(n + timedelta(seconds=20), n) == "1분"
    assert remaining_text(n, n) == "만료됨"


def test_ua_short():
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    assert ua_short(ua) == "Chrome / Windows"
    assert ua_short(None) == "알 수 없음"


# ───────── 입력 검증 ─────────
def _tpl(**over):
    base = {
        "name": "t", "updated_by": "홍길동",
        "sections": [{"title": "s", "fields": [{"label": "a", "type": "text", "value": "v"}]}],
    }
    base.update(over)
    return base


def test_template_rejects_secret_default():
    with pytest.raises(ValidationError):
        TemplateIn.model_validate(_tpl(sections=[{"title": "s", "fields": [{"label": "pw", "type": "secret", "value": "x"}]}]))
    with pytest.raises(ValidationError):
        TemplateIn.model_validate(_tpl(sections=[{"title": "s", "fields": [{"label": "k", "type": "file", "value": "x"}]}]))


def test_template_strips_and_requires_name():
    t = TemplateIn.model_validate(_tpl(name="  이름  "))
    assert t.name == "이름"
    with pytest.raises(ValidationError):
        TemplateIn.model_validate(_tpl(name="   "))


def test_delivery_requires_core_fields():
    ok = {"customer": "c", "title": "t", "owner": "o", "sections": [{"instances": [[{"label": "a", "value": "b"}]]}]}
    DeliveryIn.model_validate(ok)
    for k in ("customer", "title", "owner"):
        with pytest.raises(ValidationError):
            DeliveryIn.model_validate({**ok, k: ""})
    with pytest.raises(ValidationError):
        DeliveryIn.model_validate({**ok, "expiry": "30d"})


# ───────── 뷰 모델 ─────────
def test_build_sections_repeat_title_and_attachments():
    files_meta = [{"id": "f1", "name": "web.pem", "size": 10}, {"id": "f2", "name": "extra.zip", "size": 20}]
    sections = [{
        "title": "VM 접속 정보", "repeat": True, "unit": "VM",
        "instances": [
            [{"label": "VM 이름", "type": "text", "value": "web-01"}, {"label": "키 파일", "type": "file", "value": "web.pem", "file_id": "f1"},
             {"label": "메모", "type": "text", "value": ""}],
        ],
        "notices": [{"tone": "info", "text": "보안그룹"}, {"tone": "warn", "text": "  "}],
    }]
    out, attachments = build_sections(sections, files_meta, "real")
    inst = out[0].instances[0]
    assert inst.title_value == "web-01"
    assert [f.label for f in inst.fields] == ["키 파일"]  # 이름은 소제목으로, 빈 값은 숨김
    assert inst.fields[0].file.name == "web.pem"
    assert [a.name for a in attachments] == ["extra.zip"]
    assert len(out[0].notices) == 1


def test_preview_view_keeps_empty_fields_with_placeholder():
    p = PreviewIn.model_validate({
        "view": "reveal", "mode": "tpl",
        "meta": {"customer": "", "title": "", "owner": "", "expiry": "6h", "policy": "one_time"},
        "sections": [{"title": "", "instances": [[{"label": "키 파일", "type": "file"}, {"label": "계정", "value": "root"}]]}],
    })
    v = preview_view(p)
    fields = v.sections[0].instances[0].fields
    assert fields[0].empty and v.empty_text(fields[0]) == "등록 시 첨부"
    assert fields[1].value == "root"
    assert v.policy_chip == "1회 열람"


def test_mail_text_has_link_and_helpdesk():
    m = mail_text(customer="가온", owner="홍길동", title="VM 안내", link="https://x/s/t", deadline="2026년 1월 1일 10:00",
                  policy="until_confirmed", helpdesk="help_cloud@kinx.net")
    assert "https://x/s/t" in m and "help_cloud@kinx.net" in m and "[확인 완료]" in m
