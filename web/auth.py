"""Xác thực: băm mật khẩu + session cookie ký HMAC.

Không phụ thuộc thư viện ngoài — chỉ dùng hashlib/hmac của stdlib.

- Mật khẩu lưu dạng `salt$pbkdf2_hex` (PBKDF2-HMAC-SHA256).
- Session là cookie chứa JSON đã ký: {u, a, n, exp} + chữ ký HMAC.
  Nhờ vậy không cần truy vấn DB trên mỗi request.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

SESSION_TTL = 12 * 3600  # giây
PBKDF2_ROUNDS = 120_000

PASSWORD_ENV_KEYS = (
    "USER_A_PASSWORD",
    "USER_B_PASSWORD",
    "USER_ADJ_PASSWORD",
    "LABEL_PASSWORD",
)


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or os.urandom(16).hex()
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ROUNDS)
    return f"{salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, _ = stored.split("$", 1)
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(hash_password(password, salt), stored)


def auth_enabled() -> bool:
    """Bật khi có ít nhất một mật khẩu được cấu hình."""
    return any((os.environ.get(k) or "").strip() for k in PASSWORD_ENV_KEYS)


def _secret() -> bytes:
    explicit = (os.environ.get("SESSION_SECRET") or "").strip()
    if explicit:
        return explicit.encode()
    # Dự phòng: suy ra từ chính các mật khẩu -> đổi mật khẩu là mọi session cũ hết hiệu lực
    material = "||".join((os.environ.get(k) or "") for k in PASSWORD_ENV_KEYS)
    return hashlib.sha256(("voc-labeling||" + material).encode()).hexdigest().encode()


def password_fingerprint() -> str:
    """Dấu vân tay của cấu hình mật khẩu, dùng để biết có cần seed lại không."""
    material = "||".join((os.environ.get(k) or "") for k in PASSWORD_ENV_KEYS)
    return hashlib.sha256(material.encode()).hexdigest()


def make_token(username: str, annotator: str, display_name: str) -> str:
    payload = {
        "u": username,
        "a": annotator,
        "n": display_name,
        "exp": int(time.time()) + SESSION_TTL,
    }
    raw = base64.urlsafe_b64encode(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    sig = hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{raw}.{sig}"


def read_token(token: str | None) -> dict | None:
    if not token or "." not in token:
        return None
    raw, sig = token.rsplit(".", 1)
    expect = hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(sig, expect):
        return None
    try:
        pad = "=" * (-len(raw) % 4)
        payload = json.loads(base64.urlsafe_b64decode(raw + pad).decode())
    except Exception:
        return None
    if int(payload.get("exp", 0)) < time.time():
        return None
    return payload
