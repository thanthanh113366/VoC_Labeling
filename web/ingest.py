"""Khởi tạo SQLite + nạp 100 review từ Mau_thu_100_review_VoC.xlsx.

Chạy trực tiếp:  python ingest.py
Hoặc app.py sẽ tự gọi ensure_ready() khi khởi động.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

from config import DATA_DIR, DB_PATH, SHEET_GUIDE, SHEET_REVIEWS, XLSX_PATH
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
"""


def connect() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ingest(conn: sqlite3.Connection, force: bool = False) -> int:
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


def ensure_ready() -> None:
    conn = connect()
    try:
        ingest(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    c = connect()
    n = ingest(c, force=True)
    c.close()
    print(f"Đã nạp {n} review vào {DB_PATH}")
