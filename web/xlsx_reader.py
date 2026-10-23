"""Đọc file .xlsx bằng thư viện chuẩn (không cần openpyxl).

Chỉ hỗ trợ những gì file Mau_thu_100_review_VoC.xlsx cần: sharedStrings,
inlineStr, số, và ánh xạ tên sheet -> file XML.
"""
from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RELNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def _colnum(ref: str) -> int:
    letters = "".join(ch for ch in ref if ch.isalpha())
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    out: list[str] = []
    for si in root.findall(NS + "si"):
        out.append("".join(t.text or "" for t in si.iter(NS + "t")))
    return out


def _sheet_map(zf: zipfile.ZipFile) -> dict[str, str]:
    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rid2target = {rel.get("Id"): rel.get("Target") for rel in rels}
    mapping: dict[str, str] = {}
    for sheet in wb.iter(NS + "sheet"):
        name = sheet.get("name")
        rid = sheet.get(RELNS + "id")
        target = (rid2target.get(rid) or "").lstrip("/")
        if target and not target.startswith("xl/"):
            target = "xl/" + target
        mapping[name] = target
    return mapping


def read_workbook(path: str) -> dict[str, list[list[str]]]:
    """Trả về {tên_sheet: [[ô, ô, ...], ...]} với dòng 1 là dòng đầu tiên."""
    result: dict[str, list[list[str]]] = {}
    with zipfile.ZipFile(path) as zf:
        shared = _shared_strings(zf)
        for name, target in _sheet_map(zf).items():
            if not target:
                continue
            root = ET.fromstring(zf.read(target))
            rows: dict[int, list[str]] = {}
            for row in root.iter(NS + "row"):
                rn = int(row.get("r") or 0)
                cells: dict[int, str] = {}
                for cell in row.findall(NS + "c"):
                    ref = cell.get("r") or ""
                    ctype = cell.get("t")
                    v = cell.find(NS + "v")
                    is_el = cell.find(NS + "is")
                    val = ""
                    if ctype == "s" and v is not None and v.text is not None:
                        idx = int(v.text)
                        val = shared[idx] if idx < len(shared) else ""
                    elif ctype == "inlineStr" and is_el is not None:
                        val = "".join(t.text or "" for t in is_el.iter(NS + "t"))
                    elif v is not None and v.text is not None:
                        val = v.text
                    cells[_colnum(ref)] = val
                if cells:
                    width = max(cells) + 1
                    rows[rn] = [cells.get(i, "") for i in range(width)]
            result[name] = [rows[k] for k in sorted(rows)]
    return result


def rows_as_dicts(rows: list[list[str]]) -> list[dict[str, str]]:
    """Dòng đầu là header -> list dict."""
    if not rows:
        return []
    header = [h.strip() for h in rows[0]]
    out = []
    for r in rows[1:]:
        if not any(str(x).strip() for x in r):
            continue
        rec = {}
        for i, key in enumerate(header):
            if key:
                rec[key] = r[i] if i < len(r) else ""
        out.append(rec)
    return out
