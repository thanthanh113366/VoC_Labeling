"""Web gán nhãn 100 review — backend FastAPI.

Chạy:  ./run.sh        (hoặc ../.venv/bin/python -m uvicorn app:app --port 8765)
"""
from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

import config as C
from ingest import connect, ensure_ready


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Nạp 100 review lần đầu nếu DB chưa có dữ liệu."""
    ensure_ready()
    yield


app = FastAPI(title="VoC Labeling — Mau thu 100 review", lifespan=lifespan)

EXPORT_COLUMNS = [
    "Review_ID", "Case_ID", "Nguoi_gan_nhan", "unit_id",
    "unit_text_nguyen_van", "unit_start", "unit_end",
    "sentiment", "issue_present", "category", "severity",
    "evidence_text", "evidence_start", "evidence_end",
    "Can_thao_luan", "Ghi_chu",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _conn() -> sqlite3.Connection:
    return connect()


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _review_row(conn: sqlite3.Connection, review_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM reviews WHERE review_id = ?", (review_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"Không có review {review_id}")
    return row


def _rows_to_units(rows: list[sqlite3.Row]) -> list[dict]:
    """Gom các dòng GanNhan thành cấu trúc unit -> issues."""
    units: dict[str, dict] = {}
    order: list[str] = []
    for r in rows:
        uid = r["unit_id"] or ""
        if uid not in units:
            units[uid] = {
                "unit_id": uid,
                "start": r["unit_start"],
                "end": r["unit_end"],
                "text": r["unit_text"],
                "sentiment": r["sentiment"] or "",
                "issue_present": r["issue_present"] or "",
                "can_thao_luan": r["can_thao_luan"] or "",
                "ghi_chu": r["ghi_chu"] or "",
                "issues": [],
            }
            order.append(uid)
        if (r["category"] or "").strip():
            units[uid]["issues"].append({
                "category": r["category"],
                "severity": r["severity"] or "",
                "ev_start": r["evidence_start"],
                "ev_end": r["evidence_end"],
                "evidence": r["evidence_text"] or "",
                "can_thao_luan": r["can_thao_luan"] or "",
                "ghi_chu": r["ghi_chu"] or "",
            })
        elif (r["issue_present"] or "") == "yes":
            # dòng "chưa đủ căn cứ": có issue nhưng chưa chọn category
            units[uid]["issues"].append({
                "category": "",
                "severity": r["severity"] or "uncertain",
                "ev_start": r["evidence_start"],
                "ev_end": r["evidence_end"],
                "evidence": r["evidence_text"] or "",
                "can_thao_luan": r["can_thao_luan"] or "",
                "ghi_chu": r["ghi_chu"] or "",
            })
    return [units[u] for u in order]


def _validate_and_expand(review_text: str, payload: dict) -> list[tuple]:
    """Kiểm tra payload rồi bung thành các dòng đúng schema GanNhan."""
    units = payload.get("units") or []
    if not isinstance(units, list):
        raise HTTPException(400, "units phải là mảng")

    n = len(review_text)
    out: list[tuple] = []
    seen_units: set[str] = set()

    for i, u in enumerate(units):
        uid = str(u.get("unit_id") or f"u{i + 1}").strip() or f"u{i + 1}"
        if uid in seen_units:
            raise HTTPException(400, f"unit_id trùng: {uid}")
        seen_units.add(uid)

        try:
            start = int(u.get("start"))
            end = int(u.get("end"))
        except (TypeError, ValueError):
            raise HTTPException(400, f"{uid}: span không hợp lệ")
        if not (0 <= start < end <= n):
            raise HTTPException(400, f"{uid}: span [{start},{end}) ngoài phạm vi 0..{n}")
        unit_text = review_text[start:end]
        if not unit_text.strip():
            raise HTTPException(400, f"{uid}: span rỗng")

        sentiment = str(u.get("sentiment") or "")
        if sentiment and sentiment not in C.SENTIMENTS:
            raise HTTPException(400, f"{uid}: sentiment lạ '{sentiment}'")

        issue_present = str(u.get("issue_present") or "")
        if issue_present and issue_present not in C.ISSUE_VALUES:
            raise HTTPException(400, f"{uid}: issue_present lạ '{issue_present}'")

        # giá trị mức unit dùng làm fallback khi issue không tự khai báo
        unit_can = str(u.get("can_thao_luan") or "")
        unit_ghi = str(u.get("ghi_chu") or "")

        issues = u.get("issues") or []
        if not isinstance(issues, list):
            raise HTTPException(400, f"{uid}: issues phải là mảng")

        if issue_present == "no" or not issues:
            # một dòng đại diện unit (có thể là khen, hoặc chưa đủ căn cứ)
            can = str(u.get("can_thao_luan") or "")
            ghi = str(u.get("ghi_chu") or "")
            sev = ""
            if issue_present == "yes":
                sev = "uncertain"
                can = can or "yes"
            out.append((
                uid, unit_text, start, end, sentiment, issue_present or "no",
                "", sev, "", None, None, can, ghi,
            ))
            continue

        for j, iss in enumerate(issues):
            cat = str(iss.get("category") or "").strip()
            can_l = str(iss.get("can_thao_luan") or "") or unit_can
            ghi_l = str(iss.get("ghi_chu") or "") or unit_ghi
            if cat == "":
                # "chưa đủ căn cứ": giữ dòng uncertain thay vì từ chối
                out.append((
                    uid, unit_text, start, end, sentiment, "yes",
                    "", "uncertain", "", None, None, can_l or "yes", ghi_l,
                ))
                continue
            if cat not in C.CATEGORY_KEYS:
                raise HTTPException(400, f"{uid}: category lạ '{cat}'")
            sev = str(iss.get("severity") or "")
            if sev and sev not in C.SEVERITIES:
                raise HTTPException(400, f"{uid}: severity lạ '{sev}'")

            ev_text = ""
            ev_start = iss.get("ev_start")
            ev_end = iss.get("ev_end")
            if ev_start is not None and ev_end is not None and str(ev_start) != "" and str(ev_end) != "":
                try:
                    es, ee = int(ev_start), int(ev_end)
                except (TypeError, ValueError):
                    raise HTTPException(400, f"{uid}: evidence span không hợp lệ")
                if not (0 <= es < ee <= n):
                    raise HTTPException(400, f"{uid}: evidence span ngoài phạm vi")
                ev_text = review_text[es:ee]
                ev_start, ev_end = es, ee
            else:
                ev_start = ev_end = None

            out.append((
                uid, unit_text, start, end, sentiment, "yes",
                cat, sev, ev_text, ev_start, ev_end, can_l, ghi_l,
            ))
    return out


def _save_units(conn: sqlite3.Connection, annotator: str, review_id: str,
                case_id: str, rows: list[tuple]) -> None:
    conn.execute(
        "DELETE FROM annotations WHERE annotator = ? AND review_id = ?",
        (annotator, review_id),
    )
    ts = _now()
    for r in rows:
        conn.execute(
            """INSERT INTO annotations
               (annotator, review_id, case_id, unit_id, unit_text, unit_start, unit_end,
                sentiment, issue_present, category, severity,
                evidence_text, evidence_start, evidence_end,
                can_thao_luan, ghi_chu, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (annotator, review_id, case_id) + r + (ts,),
        )


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------
def _meta_payload(conn: sqlite3.Connection) -> dict:
    total = conn.execute("SELECT COUNT(*) AS n FROM reviews").fetchone()["n"]
    guide = conn.execute("SELECT value FROM meta WHERE key='guide'").fetchone()
    src = conn.execute("SELECT value FROM meta WHERE key='source_file'").fetchone()
    return {
        "total_reviews": total,
        "categories": [{"key": k, "label": lbl} for k, lbl in C.CATEGORIES],
        "sentiments": C.SENTIMENTS,
        "severities": C.SEVERITIES,
        "annotators": C.ANNOTATORS,
        "guide": guide["value"] if guide else "",
        "source_file": src["value"] if src else "",
    }


def _list_payload(conn: sqlite3.Connection, annotator: str) -> list[dict]:
    rows = conn.execute("""
        SELECT r.review_id, r.seq, r.case_id, r.provider, r.n_words, r.length,
               (SELECT COUNT(*) FROM annotations a
                 WHERE a.review_id = r.review_id AND a.annotator = ?) AS n_rows,
               (SELECT COUNT(*) FROM annotations a
                 WHERE a.review_id = r.review_id AND a.annotator = 'A') AS n_rows_a,
               (SELECT COUNT(*) FROM annotations a
                 WHERE a.review_id = r.review_id AND a.annotator = 'B') AS n_rows_b
          FROM reviews r
         ORDER BY r.seq
    """, (annotator,)).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/meta")
def meta():
    conn = _conn()
    try:
        return _meta_payload(conn)
    finally:
        conn.close()


@app.get("/api/reviews")
def list_reviews(annotator: str = Query("A")):
    conn = _conn()
    try:
        return _list_payload(conn, annotator)
    finally:
        conn.close()


def _review_payload(conn: sqlite3.Connection, review_id: str, annotator: str) -> dict:
    rev = dict(_review_row(conn, review_id))
    ann = conn.execute(
        "SELECT * FROM annotations WHERE annotator=? AND review_id=? ORDER BY id",
        (annotator, review_id),
    ).fetchall()
    rev["units"] = _rows_to_units(ann)
    rev["saved_rows"] = len(ann)
    return rev


@app.get("/api/reviews/{review_id}")
def get_review(review_id: str, annotator: str = Query("A")):
    conn = _conn()
    try:
        return _review_payload(conn, review_id, annotator)
    finally:
        conn.close()


@app.put("/api/reviews/{review_id}")
async def save_review(review_id: str, request: Request, annotator: str = Query("A")):
    if annotator not in C.ANNOTATORS:
        raise HTTPException(400, "annotator phải là A hoặc B")
    payload = await request.json()
    conn = _conn()
    try:
        rev = _review_row(conn, review_id)
        rows = _validate_and_expand(rev["text"], payload)
        _save_units(conn, annotator, review_id, rev["case_id"], rows)
        conn.commit()
        return {"ok": True, "rows": len(rows)}
    finally:
        conn.close()


@app.get("/api/stats")
def stats():
    conn = _conn()
    try:
        out = {}
        total = conn.execute("SELECT COUNT(*) AS n FROM reviews").fetchone()["n"]
        out["total_reviews"] = total
        for a in C.ANNOTATORS:
            done = conn.execute(
                "SELECT COUNT(DISTINCT review_id) AS n FROM annotations WHERE annotator=?",
                (a,),
            ).fetchone()["n"]
            out[a] = {"reviews_done": done, "reviews_left": total - done}
        adj = conn.execute("SELECT COUNT(*) AS n FROM adjudications").fetchone()["n"]
        out["adjudicated"] = adj
        return out
    finally:
        conn.close()


@app.get("/api/adjudicate/{review_id}")
def adjudicate_get(review_id: str):
    conn = _conn()
    try:
        rev = dict(_review_row(conn, review_id))
        sides = {}
        for a in C.ANNOTATORS:
            ann = conn.execute(
                "SELECT * FROM annotations WHERE annotator=? AND review_id=? ORDER BY id",
                (a, review_id),
            ).fetchall()
            sides[a] = _rows_to_units(ann)
        dec = conn.execute(
            "SELECT * FROM adjudications WHERE review_id=?", (review_id,)
        ).fetchone()
        rev["sides"] = sides
        rev["decision"] = json.loads(dec["decided_json"]) if dec and dec["decided_json"] else None
        rev["adjudicator"] = dec["adjudicator"] if dec else None
        return rev
    finally:
        conn.close()


@app.post("/api/adjudicate/{review_id}")
async def adjudicate_post(review_id: str, request: Request,
                          adjudicator: str = Query("ADJ")):
    payload = await request.json()
    conn = _conn()
    try:
        rev = _review_row(conn, review_id)
        payload["units"] = payload.get("units") or []
        _validate_and_expand(rev["text"], payload)  # chỉ để kiểm tra
        conn.execute(
            """INSERT INTO adjudications(review_id, adjudicator, decided_json, updated_at)
               VALUES (?,?,?,?)
               ON CONFLICT(review_id) DO UPDATE SET
                 adjudicator=excluded.adjudicator,
                 decided_json=excluded.decided_json,
                 updated_at=excluded.updated_at""",
            (review_id, adjudicator, json.dumps(payload, ensure_ascii=False), _now()),
        )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


def _export_rows(conn: sqlite3.Connection, annotator: str,
                 adjudicated: bool = False) -> list[dict]:
    out: list[dict] = []
    if adjudicated:
        revs = conn.execute("""
            SELECT r.review_id, r.case_id, r.text, a.decided_json, a.adjudicator
              FROM reviews r JOIN adjudications a ON a.review_id = r.review_id
             ORDER BY r.seq
        """).fetchall()
        for r in revs:
            payload = json.loads(r["decided_json"] or "{}")
            rows = _validate_and_expand(r["text"], payload)
            for row in rows:
                out.append(_row_to_export(r["review_id"], r["case_id"],
                                          r["adjudicator"] or "ADJ", row))
        return out

    revs = conn.execute("""
        SELECT r.review_id, r.case_id, r.text FROM reviews r
         WHERE EXISTS (SELECT 1 FROM annotations a
                        WHERE a.review_id=r.review_id AND a.annotator=?)
         ORDER BY r.seq
    """, (annotator,)).fetchall()
    for r in revs:
        ann = conn.execute(
            "SELECT * FROM annotations WHERE annotator=? AND review_id=? ORDER BY id",
            (annotator, r["review_id"]),
        ).fetchall()
        for a in ann:
            out.append({
                "Review_ID": r["review_id"],
                "Case_ID": r["case_id"],
                "Nguoi_gan_nhan": annotator,
                "unit_id": a["unit_id"],
                "unit_text_nguyen_van": a["unit_text"],
                "unit_start": a["unit_start"],
                "unit_end": a["unit_end"],
                "sentiment": a["sentiment"],
                "issue_present": a["issue_present"],
                "category": a["category"],
                "severity": a["severity"],
                "evidence_text": a["evidence_text"],
                "evidence_start": a["evidence_start"] if a["evidence_start"] is not None else "",
                "evidence_end": a["evidence_end"] if a["evidence_end"] is not None else "",
                "Can_thao_luan": a["can_thao_luan"],
                "Ghi_chu": a["ghi_chu"],
            })
    return out


def _row_to_export(review_id: str, case_id: str, who: str, row: tuple) -> dict:
    (uid, utext, ustart, uend, senti, issue,
     cat, sev, evtext, evstart, evend, can, ghi) = row
    return {
        "Review_ID": review_id, "Case_ID": case_id, "Nguoi_gan_nhan": who,
        "unit_id": uid, "unit_text_nguyen_van": utext,
        "unit_start": ustart, "unit_end": uend,
        "sentiment": senti, "issue_present": issue, "category": cat, "severity": sev,
        "evidence_text": evtext,
        "evidence_start": evstart if evstart is not None else "",
        "evidence_end": evend if evend is not None else "",
        "Can_thao_luan": can, "Ghi_chu": ghi,
    }


@app.get("/api/export.csv")
def export_csv(annotator: str = Query("A"), adjudicated: bool = Query(False)):
    conn = _conn()
    try:
        rows = _export_rows(conn, annotator, adjudicated=adjudicated)
    finally:
        conn.close()
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=EXPORT_COLUMNS)
    w.writeheader()
    for r in rows:
        w.writerow(r)
    tag = "ADJ" if adjudicated else annotator
    filename = f"GanNhan_{tag}.csv"
    data = "\ufeff" + buf.getvalue()  # BOM để Excel đọc đúng tiếng Việt
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/export.json")
def export_json(annotator: str = Query("A"), adjudicated: bool = Query(False)):
    conn = _conn()
    try:
        rows = _export_rows(conn, annotator, adjudicated=adjudicated)
    finally:
        conn.close()
    return JSONResponse({"columns": EXPORT_COLUMNS, "rows": rows})


# --------------------------------------------------------------------------
# static
# --------------------------------------------------------------------------
@app.get("/")
def index(open_id: str | None = Query(None, alias="open")):
    """Nhúng sẵn meta + danh sách review vào HTML để trang vẽ ngay (không nhấp nháy)."""
    path = os.path.join(C.STATIC_DIR, "index.html")
    with open(path, encoding="utf-8") as fh:
        html = fh.read()

    conn = _conn()
    try:
        boot = {"meta": _meta_payload(conn), "reviews": _list_payload(conn, "A")}
        if open_id:
            try:
                boot["current"] = _review_payload(conn, open_id, "A")
            except HTTPException:
                pass
    finally:
        conn.close()

    payload = json.dumps(boot, ensure_ascii=False).replace("</", "<\\/")
    html = html.replace("<!--BOOTSTRAP-->", f"<script>window.__BOOT__={payload};</script>")
    return HTMLResponse(html)


app.mount("/static", StaticFiles(directory=C.STATIC_DIR), name="static")
