"""Hằng số dùng chung cho web gán nhãn.

Schema bám sát sheet `GanNhan` của Mau_thu_100_review_VoC.xlsx.
"""
from __future__ import annotations

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LABELING_DIR = os.path.dirname(BASE_DIR)


def _load_dotenv() -> None:
    """Nạp .env (nếu có) vào os.environ. Không ghi đè biến đã được set."""
    for path in (os.path.join(BASE_DIR, ".env"), os.path.join(LABELING_DIR, ".env")):
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = value
        except OSError:
            pass


_load_dotenv()

# File mẫu có thể nằm cạnh app.py (khi deploy Vercel, Root Directory = web)
# hoặc ở gốc repo (khi chạy local) -> dò cả hai.
_XLSX_CANDIDATES = [
    os.path.join(BASE_DIR, "Mau_thu_100_review_VoC.xlsx"),
    os.path.join(LABELING_DIR, "Mau_thu_100_review_VoC.xlsx"),
]
XLSX_PATH = next((p for p in _XLSX_CANDIDATES if os.path.exists(p)), _XLSX_CANDIDATES[0])

DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "labeling.db")
STATIC_DIR = os.path.join(BASE_DIR, "static")

SHEET_REVIEWS = "Mau100"
SHEET_GUIDE = "HuongDan"
# Sheet LyDoChon cố ý KHÔNG được nạp: đó là gợi ý từ khóa, không phải nhãn,
# và phải ẩn để hai người gán nhãn độc lập (blind).

# 11 macro quality determinant MOBI-Qual + other (khớp gold_label_codebook.md)
CATEGORIES = [
    ("customer_service", "Customer service"),
    ("app_reliability", "App reliability"),
    ("charges_fees", "Charges and fees"),
    ("vehicle_conditions", "Vehicle conditions"),
    ("sharing_benefits", "Sharing benefits"),
    ("physical_accessibility", "Physical accessibility"),
    ("parking_area", "Parking area"),
    ("safety", "Safety"),
    ("ease_of_use", "Ease of use"),
    ("digital_accessibility", "Digital accessibility"),
    ("payments", "Payments"),
    ("other", "Other"),
]
CATEGORY_KEYS = [k for k, _ in CATEGORIES]

SENTIMENTS = ["positive", "neutral", "negative"]
ISSUE_VALUES = ["yes", "no"]
# not_applicable / uncertain do chính file mẫu bổ sung so với codebook
SEVERITIES = ["low", "medium", "high", "not_applicable", "uncertain"]
ANNOTATORS = ["A", "B"]
