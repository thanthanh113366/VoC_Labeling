"""Khởi tạo CSDL + nạp 100 review từ Mau_thu_100_review_VoC.xlsx.

Chạy trực tiếp:  python ingest.py
Hoặc app.py sẽ tự gọi ensure_ready() khi khởi động.

CSDL là Turso nếu có TURSO_DATABASE_URL, ngược lại là file SQLite local.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from config import DB_PATH, SHEET_GUIDE, SHEET_REVIEWS, XLSX_PATH
from db import Connection, connect
from xlsx_reader import read_workbook, rows_as_dicts

SCHEMA = """
CREATE TABLE IF NOT EXISTS reviews (
    review_id   TEXT PRIMARY KEY,
    seq         INTEGER,
    case_id     TEXT,
    provider    TEXT,
    date        TEXT,
    source      TEXT,
    text        TEXT NOT NULL,
    country     TEXT,
    type_meta   TEXT,
    n_words     TEXT,
    length      TEXT,
    sheet       TEXT,
    excel_row   TEXT
);

CREATE TABLE IF NOT EXISTS annotations (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    annotator      TEXT NOT NULL,
    review_id      TEXT NOT NULL,
    case_id        TEXT,
    unit_id        TEXT,
    unit_text      TEXT,
    unit_start     INTEGER,
    unit_end       INTEGER,
    sentiment      TEXT,
    issue_present  TEXT,
    category       TEXT,
    severity       TEXT,
    evidence_text  TEXT,
    evidence_start INTEGER,
    evidence_end   INTEGER,
    can_thao_luan  TEXT,
    ghi_chu        TEXT,
    updated_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_ann_owner ON annotations(annotator, review_id);

CREATE TABLE IF NOT EXISTS adjudications (
    review_id    TEXT PRIMARY KEY,
    adjudicator  TEXT,
    decided_json TEXT,
    updated_at   TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS users (
    username      TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    annotator     TEXT NOT NULL,
    display_name  TEXT,
    updated_at    TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ingest(conn: Connection, force: bool = False) -> int:
    """Nạp reviews + hướng dẫn. Trả về số review đã nạp."""
    conn.executescript(SCHEMA)

    if not force:
        row = conn.execute("SELECT COUNT(*) AS n FROM reviews").fetchone()
        if row and row["n"] > 0:
            return int(row["n"])

    if not os.path.exists(XLSX_PATH):
        raise FileNotFoundError(f"Không thấy file mẫu: {XLSX_PATH}")

    book = read_workbook(XLSX_PATH)

    # ---- 100 review ----
    rev_rows = book.get(SHEET_REVIEWS, [])
    records = rows_as_dicts(rev_rows)

    conn.execute("DELETE FROM reviews")
    seq = 0
    for rec in records:
        rid = str(rec.get("Review_ID", "")).strip()
        if not rid:
            continue
        seq += 1
        conn.execute(
            """INSERT OR REPLACE INTO reviews
               (review_id, seq, case_id, provider, date, source, text,
                country, type_meta, n_words, length, sheet, excel_row)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                rid,
                seq,
                str(rec.get("Case_ID", "")).strip(),
                str(rec.get("Provider", "")).strip(),
                str(rec.get("Date", "")).strip(),
                str(rec.get("Source", "")).strip(),
                str(rec.get("Review_nguyen_van", "")),
                str(rec.get("Country_metadata", "")).strip(),
                str(rec.get("Type_metadata", "")).strip(),
                str(rec.get("So_tu", "")).strip(),
                str(rec.get("Do_dai", "")).strip(),
                str(rec.get("Sheet_nguon", "")).strip(),
                str(rec.get("Dong_Excel", "")).strip(),
            ),
        )

    # ---- hướng dẫn (hiển thị trong tab trợ giúp) ----
    guide_lines: list[str] = []
    for raw in book.get(SHEET_GUIDE, []):
        parts = [str(c).strip() for c in raw if str(c).strip()]
        if parts:
            guide_lines.append("  —  ".join(parts))
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
        ("guide", "\n".join(guide_lines)),
    )
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
        ("source_file", os.path.basename(XLSX_PATH)),
    )
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
        ("ingested_at", _now()),
    )
    conn.commit()
    return seq


def seed_users(conn: Connection) -> int:
    """Tạo/cập nhật tài khoản từ biến môi trường.

    - USER_A_PASSWORD   -> tài khoản người A (annotator = A)
    - USER_B_PASSWORD   -> tài khoản người B (annotator = B)
    - USER_ADJ_PASSWORD -> tài khoản hòa giải (annotator = ADJ)
    - LABEL_PASSWORD    -> nếu không có gì ở trên: một tài khoản admin (ADJ)

    Tên đăng nhập đổi được bằng USER_A_NAME / USER_B_NAME / USER_ADJ_NAME.
    Chỉ băm lại mật khẩu khi cấu hình thực sự thay đổi (so dấu vân tay),
    nhờ vậy cold start không phải chạy PBKDF2 mỗi lần.
    """
    from auth import hash_password, password_fingerprint

    a_pw = (os.environ.get("USER_A_PASSWORD") or "").strip()
    b_pw = (os.environ.get("USER_B_PASSWORD") or "").strip()
    adj_pw = (os.environ.get("USER_ADJ_PASSWORD") or "").strip()
    legacy = (os.environ.get("LABEL_PASSWORD") or "").strip()

    def name(key: str, default: str) -> str:
        return (os.environ.get(key) or "").strip() or default

    accounts: list[tuple[str, str, str, str]] = []
    if a_pw:
        accounts.append((name("USER_A_NAME", "a"), a_pw, "A", "Người A"))
    if b_pw:
        accounts.append((name("USER_B_NAME", "b"), b_pw, "B", "Người B"))
    if adj_pw:
        accounts.append((name("USER_ADJ_NAME", "adj"), adj_pw, "ADJ", "Hòa giải"))
    if not accounts and legacy:
        accounts.append((name("USER_ADMIN_NAME", "admin"), legacy, "ADJ", "Quản trị"))

    if not accounts:
        return 0

    fp = password_fingerprint()
    row = conn.execute("SELECT value FROM meta WHERE key = 'pw_fingerprint'").fetchone()
    if row and row["value"] == fp:
        return len(accounts)  # cấu hình không đổi -> khỏi băm lại

    for username, password, annotator, display in accounts:
        conn.execute(
            """INSERT INTO users(username, password_hash, annotator, display_name, updated_at)
               VALUES (?,?,?,?,?)
               ON CONFLICT(username) DO UPDATE SET
                 password_hash = excluded.password_hash,
                 annotator     = excluded.annotator,
                 display_name  = excluded.display_name,
                 updated_at    = excluded.updated_at""",
            (username, hash_password(password), annotator, display, _now()),
        )
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES ('pw_fingerprint', ?)", (fp,)
    )
    conn.commit()
    return len(accounts)


def ensure_ready() -> None:
    conn = connect()
    try:
        ingest(conn)
        seed_users(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    from db import backend_name
    c = connect()
    n = ingest(c, force=True)
    c.close()
    print(f"Đã nạp {n} review — backend: {backend_name()}")
