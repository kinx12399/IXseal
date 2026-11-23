"""봉투 암호화와 링크 토큰.

- 시크릿마다 DEK(256bit)를 만들고 내용과 파일을 AES-256-GCM으로 암호화한다.
- DEK는 KEK로 감싸 저장한다. KEK는 DB가 아니라 VM 파일에 둔다.
- 암호문 형식: nonce(12바이트) || ciphertext+tag
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import uuid
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_LEN = 12
TOKEN_BYTES = 32  # base64url 43자


class CryptoError(Exception):
    pass


class KeyRing:
    """KEK 파일: 한 줄에 `<id>:<base64 32바이트>`. 가장 큰 id가 현재 키이고, 나머지는 옛 키 복호화용."""

    def __init__(self, keys: dict[int, bytes]):
        if not keys:
            raise CryptoError("KEK가 없습니다")
        for kid, key in keys.items():
            if len(key) != 32:
                raise CryptoError(f"KEK {kid}의 길이가 32바이트가 아닙니다")
        self._keys = dict(keys)
        self.current_id = max(keys)

    @classmethod
    def load(cls, path: str | Path) -> "KeyRing":
        keys: dict[int, bytes] = {}
        for raw in Path(path).read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            kid, _, b64 = line.partition(":")
            keys[int(kid)] = base64.b64decode(b64, validate=True)
        return cls(keys)

    def wrap(self, dek: bytes, aad: bytes) -> tuple[int, bytes]:
        return self.current_id, seal(self._keys[self.current_id], dek, aad)

    def unwrap(self, kek_id: int, blob: bytes, aad: bytes) -> bytes:
        key = self._keys.get(kek_id)
        if key is None:
            raise CryptoError(f"KEK {kek_id}를 찾을 수 없습니다")
        return unseal(key, blob, aad)


def new_kek_line(kek_id: int) -> str:
    return f"{kek_id}:{base64.b64encode(os.urandom(32)).decode()}"


def new_dek() -> bytes:
    return AESGCM.generate_key(bit_length=256)


def seal(key: bytes, plaintext: bytes, aad: bytes) -> bytes:
    nonce = os.urandom(NONCE_LEN)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, aad)


def unseal(key: bytes, blob: bytes, aad: bytes) -> bytes:
    if len(blob) < NONCE_LEN + 16:
        raise CryptoError("암호문이 손상되었습니다")
    try:
        return AESGCM(key).decrypt(blob[:NONCE_LEN], blob[NONCE_LEN:], aad)
    except Exception as exc:  # InvalidTag
        raise CryptoError("복호화에 실패했습니다") from exc


# AAD: 암호문을 다른 행에 옮겨 붙이는 것을 막는다
def aad_dek(secret_id: uuid.UUID) -> bytes:
    return b"ixseal:dek:" + secret_id.bytes


def aad_payload(secret_id: uuid.UUID) -> bytes:
    return b"ixseal:payload:" + secret_id.bytes


def aad_file(secret_id: uuid.UUID, file_id: uuid.UUID) -> bytes:
    return b"ixseal:file:" + secret_id.bytes + file_id.bytes


def pack_file(name: str, data: bytes) -> bytes:
    """파일명과 내용을 함께 암호화하기 위한 평문 형식: 이름 길이(2바이트) || 이름 || 내용"""
    raw = name.encode("utf-8")
    return len(raw).to_bytes(2, "big") + raw + data


def unpack_file(plain: bytes) -> tuple[str, bytes]:
    n = int.from_bytes(plain[:2], "big")
    return plain[2 : 2 + n].decode("utf-8"), plain[2 + n :]


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode("ascii")).digest()


def looks_like_token(token: str) -> bool:
    return len(token) == 43 and all(c.isalnum() or c in "-_" for c in token) and token.isascii()
