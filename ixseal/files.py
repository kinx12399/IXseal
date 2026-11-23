"""첨부 파일 검사. 형식은 넓게 허용하되 실행 파일·스크립트는 막는다."""

from __future__ import annotations

import re

BLOCKED_EXTENSIONS = frozenset(
    """
    exe msi msp bat cmd com scr pif cpl ps1 psm1 psd1 vbs vbe js jse wsf wsh hta lnk
    jar sh bash zsh csh ksh bin run app dmg pkg apk dll so dylib sys drv ocx reg
    """.split()
)

# 실행 파일 매직 바이트 (확장자를 바꿔도 막는다)
_MAGIC = (
    (b"MZ", "Windows 실행 파일"),
    (b"\x7fELF", "Linux 실행 파일"),
    (b"\xfe\xed\xfa\xce", "macOS 실행 파일"),
    (b"\xfe\xed\xfa\xcf", "macOS 실행 파일"),
    (b"\xce\xfa\xed\xfe", "macOS 실행 파일"),
    (b"\xcf\xfa\xed\xfe", "macOS 실행 파일"),
    (b"\xca\xfe\xba\xbe", "macOS/Java 실행 파일"),
    (b"#!", "스크립트"),
)

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class UploadError(ValueError):
    pass


def sanitize_filename(name: str) -> str:
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = _CONTROL.sub("", name).strip().strip(".")
    if not name:
        name = "file"
    raw = name.encode("utf-8")
    if len(raw) > 200:
        stem, dot, ext = name.rpartition(".")
        ext = ext if dot and len(ext) <= 10 else ""
        keep = 200 - len(ext.encode()) - 1
        stem = (stem or name).encode("utf-8")[:keep].decode("utf-8", "ignore")
        name = f"{stem}.{ext}" if ext else stem
    return name


def extension(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def check_file(name: str, data: bytes, max_bytes: int) -> None:
    ext = extension(name)
    if ext in BLOCKED_EXTENSIONS:
        raise UploadError(f"실행 파일·스크립트(.{ext})는 올릴 수 없습니다: {name}")
    for magic, kind in _MAGIC:
        if data.startswith(magic):
            raise UploadError(f"{kind}은(는) 올릴 수 없습니다: {name}")
    if len(data) == 0:
        raise UploadError(f"빈 파일입니다: {name}")
    if len(data) > max_bytes:
        raise UploadError(f"파일이 너무 큽니다({human_size(len(data))}): {name}")


def check_files(files: list[tuple[str, bytes]], *, max_files: int, max_file_bytes: int, max_total_bytes: int) -> None:
    if len(files) > max_files:
        raise UploadError(f"파일은 {max_files}개까지 올릴 수 있습니다")
    total = 0
    for name, data in files:
        check_file(name, data, max_file_bytes)
        total += len(data)
    if total > max_total_bytes:
        raise UploadError(f"파일 전체 크기는 {human_size(max_total_bytes)}까지입니다")


def human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.1f} MB"
