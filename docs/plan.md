# Kế hoạch xây Web gán nhãn mẫu dữ liệu VoC (MOBI-Qual)

> Kết hợp `Digital VoC Dataset.xlsx` (54.816 reviews, 3 mode shared mobility) với `chon_mo_hinh_pipeline_VoC.pdf` (pipeline 8 bước, mỗi bước cần gold set riêng) để xây web gán nhãn.
> Schema nhãn chi tiết: xem [`gold_label_codebook.md`](gold_label_codebook.md). Danh sách mẫu cụ thể: [`labeling_sample_plan.csv`](labeling_sample_plan.csv).

---

## 1. Bối cảnh & mục tiêu

Pipeline cần **gold set có nhãn tay** để: (a) chọn mô hình cho từng bước, (b) fine-tune LoRA, (c) đo chỉ số cuối cùng. Web gán nhãn giúp 2 annotator gán nhãn độc lập + 1 adjudicator hòa giải, xuất ra gold JSONL cho từng bước.

**Dữ liệu nguồn — 3 sheet trong xlsx:**

| Sheet (mode) | Số review | Cột | Provider |
|---|---|---|---|
| Car sharing | 11.127 | ID, Fonte, Country, Provider, Type, Data, Rating, Review | Zipcar, Car2go, DriveNow, … (10) |
| Bike sharing | 16.406 | Service, Website, Type, State, Date, Review | Lime, Citi Bike, Nextbike, Santander, … (27) |
| E-scooter sharing | 27.189 | Service, Website, Type, Username, State, Date, Review | Bird, Spin, Lime, voi, Tier, … (16) |
| **Tổng** | **54.722** | — | — |

> ⚠️ **Lưu ý quan trọng:** cột `Type` = *loại chia sẻ* (`Station based` / `Free floating` / `Docked` / `Dockless` / `Mixed`), **KHÔNG phải sentiment**. Sentiment và mọi nhãn pipeline (unit, issue, severity, evidence) đều **chưa có** — đây chính là việc web cần làm.
> Review đa ngôn ngữ (nhiều quốc gia), cần thống kê tỷ lệ non-English trước khi chạy (ưu tiên mô hình đa ngôn ngữ theo PDF).

---

## 2. Các lớp nhãn cần gán (ánh xạ pipeline)

| Bước pipeline | Lớp nhãn | Cấp | Mô hình sẽ dùng gold này để |
|---|---|---|---|
| 1 | Opinion units (span) | review | chọn LLM tách ý |
| 2 | Sentiment (pos/neu/neg) | unit | chọn encoder/LLM sentiment |
| 3 | Issue present + Category (11 MOBI-Qual) | unit | chọn LLM multi-label |
| 4 | Severity (low/med/high) | issue | LoRA fine-tune |
| 5 | Evidence (span nguyên văn) | issue | chọn LLM extractive |
| 6 | Insight (top 2) | case | chọn LLM tổng hợp |
| 7 | Recommendation (top 2) | case | chọn LLM khuyến nghị |
| 8 | Verifier (supported/partial/unsupported) | claim | đánh giá verifier |

→ Web phải hỗ trợ **đủ 5 lớp review-level + 3 lớp case-level** (schema đầy đủ ở codebook).

---

## 3. Kế hoạch lấy mẫu & danh sách mẫu (đã sinh sẵn)

Đã sinh file **`labeling_sample_plan.csv`** (390 dòng, deterministic seed — chạy lại cho kết quả y hệt). Phương pháp: **phân tầng theo mode (130/mode) và tỷ lệ theo provider (largest-remainder, đảm bảo ≥1/provider)**, 3 tập không trùng nhau.

| Tập | Số mẫu | Mục đích |
|---|---|---|
| `pilot` | 60 (20/mode) | Hiệu chỉnh codebook + đo IAA trước khi gán quy mô lớn |
| `dev` | 240 (80/mode) | Tuning prompt / few-shot / LoRA |
| `test` | 90 (30/mode) | Held-out — không đụng tới, chạy 1 lần cuối |
| **Case-level** | **~24 cases** | Chọn provider × quý từ dev, gán insight/recommendation/verifier |

**Quy trình gán nhãn đề xuất:**
1. Gán `pilot` (60) với 2 annotator → tính IAA → adjudicate → **đóng băng codebook** → gán lại pilot nếu codebook đổi.
2. Gán `dev` (240) theo codebook đã đóng băng.
3. `test` (90) giữ nguyên, không gán nhãn tới khi khóa cấu hình mô hình.
4. Case-level gán sau cùng (cần bảng tổng hợp từ dev).

---

## 4. Kiến trúc web app

**Tái sử dụng stack sẵn có** của dự án: FastAPI (`api/`) + SQLite (`store/`) + frontend HTML tĩnh (giống `dashboard/index.html`). Không cần framework frontend mới.

```
labeling/                      # module mới (backend)
├── ingest.py                  # đọc xlsx → chuẩn hóa 3 sheet → bảng reviews
├── routes.py                  # API gán nhãn
├── iaa.py                     # tính Cohen's/weighted kappa, F1 span
└── export.py                  # xuất gold JSONL theo từng bước pipeline

labeling_web/index.html        # SPA gán nhãn (tĩnh, fetch API)
```

### 4.1 Database (mở rộng `store/schema.sql`)

| Bảng | Vai trò |
|---|---|
| `reviews` | Chuẩn hóa từ xlsx: `review_id`, `mode`, `provider`, `sharing_type`, `source`, `country`, `date`, `rating`, `text` |
| `gold_sets` | `set` ∈ {pilot, dev, test}, nạp từ `labeling_sample_plan.csv` |
| `annotators` | `id`, `role` ∈ {admin, annotator, adjudicator}, `name` |
| `assignments` | `sample_id`, `annotator_id`, `status` ∈ {assigned, in_progress, done} |
| `annotations` | Kết quả JSON (5 lớp review-level), `annotator_id`, `review_id`, `version` |
| `case_annotations` | Kết quả JSON (3 lớp case-level) |
| `adjudications` | Quyết định hòa giải + `decision_status` |

### 4.2 API endpoints

| Method | Path | Chức năng |
|---|---|---|
| POST | `/labeling/ingest` | Nạp xlsx → chuẩn hóa → bảng reviews + gold_sets |
| GET | `/labeling/queue?annotator_id=` | Lấy danh sách mẫu được phân công (blind — không thấy nhãn người kia) |
| GET | `/labeling/review/{review_id}` | Lấy review + metadata |
| POST | `/labeling/annotation` | Lưu nhãn (validate: span phải là substring, enum hợp lệ) |
| GET | `/labeling/adjudicate/{review_id}` | Xem song song nhãn A/B |
| POST | `/labeling/adjudicate` | Lưu quyết định hòa giải |
| GET | `/labeling/iaa?set=` | Báo cáo đồng thuận (kappa/F1) |
| GET | `/labeling/export/{step}` | Xuất gold JSONL cho từng bước (1–8) |

### 4.3 Các màn hình UI

1. **Đăng nhập / chọn vai** (annotator A, annotator B, adjudicator, admin).
2. **Hàng đợi mẫu** — tiến độ, mẫu đã/đang/chưa gán.
3. **Màn gán nhãn (lõi)** — review text bên trái; bên phải:
   - bôi đen span → tạo unit (lớp 1),
   - chọn sentiment cho từng unit (lớp 2),
   - chọn issue present + category (dropdown 11 determinant, multi-select) (lớp 3),
   - chọn severity (lớp 4),
   - bôi đen evidence span — **client kiểm tra ngay substring + chặn diễn giải lại** (lớp 5).
4. **Màn hòa giải** — hiển thị A vs B song song, chọn/ghép nhãn, ghi lý do.
5. **Màn case-level** — bảng tổng hợp category×severity (code tính sẵn) → gán 2 insight + 2 recommendation + verifier.
6. **Dashboard IAA** — kappa theo lớp, tiến độ theo annotator.

---

## 5. Lộ trình triển khai

| Giai đoạn | Việc cần làm | Đầu ra |
|---|---|---|
| M0 — Ingest | `ingest.py` đọc xlsx, chuẩn hóa 3 schema, tạo `review_id` ổn định | bảng `reviews` + `gold_sets` |
| M1 — Backend | API gán nhãn + validation span/enum + lưu JSON | chạy được qua curl |
| M2 — UI review-level | Màn gán nhãn 5 lớp (bôi đen span + dropdown) | gán được pilot |
| M3 — IAA + adjudication | Tính kappa/F1, màn hòa giải | báo cáo đồng thuận pilot |
| M4 — UI case-level | Bảng tổng hợp → insight/recommendation/verifier | gán được case |
| M5 — Export | JSONL theo từng bước + manifest `review_id` | gold set nạp vào pipeline |
| M6 — Pilot thật | 2 annotator gán 60 mẫu → IAA → đóng băng codebook | codebook v1 + chỉ số IAA |

---

## 6. Rủi ro & lưu ý

- **Span phải nguyên văn** — lỗi diễn giải lại/bịa là rủi ro lớn nhất ở bước 5 (PDF nhấn mạnh); web phải chặn bằng kiểm tra substring.
- **Nhãn severity nhiễu** — chủ quan nhất; IAA sẽ thấp, cân nhắc gộp 2 mức nếu mẫu ít.
- **Đa ngôn ngữ** — thống kê tỷ lệ non-English trước, ưu tiên mô hình đa ngôn ngữ.
- **Lỗi lan truyền** — lỗi ở lớp 1 lan xuống mọi lớp; khi export phải giữ `review_id` + `unit_id` để truy vết từng stage.
- **Trần chất lượng** — không đặt kỳ vọng mô hình vượt độ đồng thuận annotator (nhất là severity).
- **Không claim outcome** — dataset không có outcome thực tế, insight/recommendation không được suy diễn tác động kinh doanh.

---

## 7. Câu hỏi chờ quyết định trước khi code

1. **Quy mô:** 390 review-level có đủ không, hay cần gấp đôi (dev 500+) cho LoRA trên nhãn hiếm?
2. **Ngôn ngữ gán nhãn:** gán nhãn trên review gốc (EN) hay dịch? (khuyến nghị: gán trên gốc, annotator đọc EN).
3. **Vai trò annotator:** 2 người thật, hay dùng LLM làm annotator + người adjudicate (khớp triết lý codebook cũ của dự án)?
4. **Case-level:** chọn bao nhiêu case và khoảng thời gian nào (quý/năm) để làm bảng tổng hợp?
