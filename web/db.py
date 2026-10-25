"""Lớp truy cập CSDL — chạy được cả local lẫn Vercel.

- Có `TURSO_DATABASE_URL`  → dùng Turso (SQLite qua mạng, bền trên serverless)
- Không có                 → dùng file SQLite local (`web/data/labeling.db`)

Cả hai đường đều được bọc về cùng một giao diện giống `sqlite3`:
`execute()` trả cursor có `fetchone()` / `fetchall()` / duyệt được,
mỗi dòng là dict nên đọc được `row["col"]` lẫn `row[0]`.
"""
from __future__ import annotations

import os
import sqlite3
import threading

import config as C

TURSO_URL = (os.environ.get("TURSO_DATABASE_URL") or "").strip()
TURSO_TOKEN = (os.environ.get("TURSO_AUTH_TOKEN") or "").strip()
IS_REMOTE = bool(TURSO_URL)


class Row(dict):
    """dict nhưng vẫn truy cập được theo chỉ số như sqlite3.Row."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


def _wrap(description, values):
    if values is None:
        return None
    if description:
        return Row(zip([d[0] for d in description], values))
    return Row((str(i), v) for i, v in enumerate(values))


class Cursor:
    def __init__(self, cur):
        self._cur = cur

    def fetchone(self):
        return _wrap(self._cur.description, self._cur.fetchone())

    def fetchall(self):
        desc = self._cur.description
        return [_wrap(desc, r) for r in self._cur.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())


def _split_statements(script: str) -> list[str]:
    return [s.strip() for s in script.split(";") if s.strip()]


class Connection:
    def __init__(self, raw):
        self._raw = raw

    def execute(self, sql, params=()):
        return Cursor(self._raw.execute(sql, params))

    def executescript(self, script: str) -> None:
        # Turso không có executescript -> chạy từng câu
        for stmt in _split_statements(script):
            self._raw.execute(stmt)

    def commit(self) -> None:
        self._raw.commit()

    def close(self) -> None:
        """Kết thúc một lượt dùng: rollback giao dịch dở dang, giữ raw để tái dùng theo thread."""
        try:
            self._raw.rollback()
        except Exception:
            pass


def _connect_remote() -> Connection:
    url = TURSO_URL
    try:
        if url.startswith("libsql://"):
            import libsql  # DB-API, giống sqlite3
            return Connection(libsql.connect(database=url, auth_token=TURSO_TOKEN))
        if url.startswith(("turso://", "https://", "http://")):
            import turso_serverless
            return Connection(turso_serverless.connect(url, auth_token=TURSO_TOKEN))
    except ImportError as exc:  # thiếu package
        raise RuntimeError(
            "Thiếu driver Turso. Cài thêm:\n"
            "  libsql://...  -> pip install libsql\n"
            "  turso://...   -> pip install turso_serverless"
        ) from exc
    raise RuntimeError(
        f"TURSO_DATABASE_URL có scheme không hỗ trợ: {url[:16]}... "
        "(cần libsql:// hoặc turso://)"
    )


_thread_local = threading.local()


def _open() -> Connection:
    """Mở một connection mới: Turso nếu có cấu hình, ngược lại SQLite local."""
    if IS_REMOTE:
        return _connect_remote()
    os.makedirs(C.DATA_DIR, exist_ok=True)  # Vercel chỉ cho ghi ở /tmp -> bỏ qua
    raw = sqlite3.connect(C.DB_PATH)
    raw.row_factory = sqlite3.Row
    return Connection(raw)


def connect() -> Connection:
    """Trả về connection tái dùng theo thread, tránh mở/handshake mỗi request."""
    conn = getattr(_thread_local, "conn", None)
    if conn is None:
        conn = _open()
        _thread_local.conn = conn
    return conn


def backend_name() -> str:
    if not IS_REMOTE:
        return "sqlite"
    return "turso-libsql" if TURSO_URL.startswith("libsql://") else "turso"
