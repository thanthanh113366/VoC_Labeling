# VoC Labeling — Web gán nhãn dữ liệu Voice-of-Customer

Công cụ gán nhãn thủ công cho **100 review mẫu** (MOBI-Qual, e-scooter, Q3/2021), phục vụ xây gold set cho pipeline VoC 8 bước.

Hai người gán nhãn độc lập (A/B) → hòa giải → xuất CSV đúng schema `GanNhan`.

---

## Cài đặt & chạy

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

cd web
./run.sh                 # mặc định http://127.0.0.1:8765
# hoặc: PORT=9000 ./run.sh
```

Lần chạy đầu tự nạp 100 review từ `Mau_thu_100_review_VoC.xlsx` vào `web/data/labeling.db`.

Nạp lại từ đầu:

```bash
cd web && ../.venv/bin/python ingest.py
```

---

## Giao diện

**Danh sách 100 review, nhóm theo case:**

![Danh sách review](web/screenshots/01-danh-sach-review.png)

**Đang gán nhãn — unit màu vàng, bằng chứng màu xanh:**

![Editor đã gán nhãn](web/screenshots/03-editor-da-gan-nhan.png)

---

## Quy trình 3 vai

| Vai | Cách dùng |
|---|---|
| **Người A** | Bấm "Người A" → gán 100 review → Xuất CSV |
| **Người B** | Bấm "Người B" → gán **độc lập** (không thấy nhãn của A) |
| **Hòa giải** | Tab "Hòa giải" → xem A và B song song → chọn A hoặc B |

Vai được lưu trong `localStorage` của trình duyệt.

---

## Gán nhãn một review

1. Chọn review ở cột trái.
2. **Bôi đen** một đoạn trong khung review → bấm **+ Tạo unit** (hoặc `Ctrl+Enter`).
3. Chọn **Sentiment**, **Có vấn đề?**.
4. Nếu có vấn đề: thêm **Nhóm lỗi** (11 MOBI-Qual + `other`), chọn **Severity**.
5. Bấm **Chọn bằng chứng** → bôi đen đoạn văn chứng minh.
6. **Lưu nhãn** (`Ctrl+S`).

Phím tắt: `Ctrl+S` lưu · `Ctrl+Enter` tạo unit.

---

## Ánh xạ sang sheet `GanNhan`

| Cột Excel | Nguồn trong app |
|---|---|
| `Review_ID`, `Case_ID` | từ DB |
| `Nguoi_gan_nhan` | A / B / ADJ |
| `unit_id`, `unit_text_nguyen_van`, `unit_start`, `unit_end` | vùng bôi đen (offset từ 0) |
| `sentiment` | dropdown positive / neutral / negative |
| `issue_present` | dropdown yes / no |
| `category` | 11 nhóm MOBI-Qual + `other` |
| `severity` | low / medium / high / not_applicable / uncertain |
| `evidence_text`, `evidence_start`, `evidence_end` | vùng bôi đen bằng chứng |
| `Can_thao_luan`, `Ghi_chu` | ô nhập ở mức unit |

Một unit nhiều nhóm lỗi → xuất thành nhiều dòng (đúng quy ước "mỗi hàng là một unit–category").

---

## Xuất dữ liệu

| Endpoint | Nội dung |
|---|---|
| `GET /api/export.csv?annotator=A` | CSV UTF-8 (có BOM), 16 cột đúng `GanNhan` |
| `GET /api/export.csv?annotator=A&adjudicated=true` | bản đã hòa giải |
| `GET /api/export.json?annotator=A` | cùng dữ liệu dạng JSON |
| `GET /api/stats` | tiến độ từng người |

Nút **Xuất CSV** trên thanh công cụ tải trực tiếp.

---

## Cấu trúc

```
.
├── Mau_thu_100_review_VoC.xlsx    # 4 sheet: HuongDan, Mau100, LyDoChon, GanNhan
├── docs/
│   ├── codebook.md                # 8 lớp nhãn + 11 MOBI-Qual determinants + ví dụ mẫu
│   └── plan.md                    # kế hoạch xây web, kiến trúc, lộ trình
├── sample_plan_390.csv            # đề xuất 390 mẫu cho bộ dữ liệu đầy đủ (3 mode)
└── web/
    ├── app.py                     # FastAPI: API + SSR bootstrap
    ├── ingest.py                  # xlsx → SQLite
    ├── xlsx_reader.py             # đọc xlsx bằng thư viện chuẩn
    ├── config.py                  # đường dẫn + danh mục nhãn
    ├── run.sh
    ├── static/                    # index.html, app.js, style.css
    ├── screenshots/
    └── data/labeling.db           # sinh tự động, KHÔNG commit
```

---

## Quyết định thiết kế

**1. Sheet `LyDoChon` không được nạp.** Đó là gợi ý từ khóa, không phải nhãn. Nạp vào sẽ làm người gán bị thiên lệch, trái yêu cầu "làm độc lập" trong sheet `HuongDan`.

**2. Offset tính bằng code point, không phải UTF-16.** Ba review có emoji khiến `len()` của Python khác `.length` của JavaScript. Client chuyển vị trí bôi đen sang code point; server tự cắt `unit_text` từ span nên không bao giờ lệch.

**3. Bằng chứng không cho gõ tay.** Client chỉ gửi span; server cắt nguyên văn từ review → `evidence_text` luôn là chuỗi con thật.

**4. A và B tách tuyệt đối.** `GET /api/reviews/{id}?annotator=A` chỉ trả nhãn của A.

---

## Đã kiểm chứng

- Nạp đúng 100 review, 20/case, 20/provider (Bird, Spin, Lime, Tier, voi).
- Round-trip lưu/đọc cả 100 review: 0 lỗi, `unit_text` luôn khớp `text[start:end]`.
- Chặn span ngoài phạm vi và `category` lạ (HTTP 400).
- Giữ nguyên emoji (77 code point / 81 UTF-16).
- CSV khớp đúng 16 cột của `GanNhan`, kể cả bản hòa giải.

---

## Chưa làm

- **Case-level (bước 6–8)**: insight, recommendation, verifier — xem `docs/plan.md`.
- Hòa giải hiện chọn trọn A hoặc trọn B, chưa ghép từng unit.
- Chưa xuất `.xlsx` trực tiếp (đang CSV).
- Chưa có đăng nhập.
- Chưa deploy (dự kiến Vercel + Turso).

---

## Nguồn dữ liệu

`Mau_thu_100_review_VoC.xlsx` — trích từ bộ **MOBI-Qual** (Barravecchia et al., 2024), lọc còn 100 review e-scooter Q3/2021 thuộc 5 provider. Không chứa username hay thông tin cá nhân.
