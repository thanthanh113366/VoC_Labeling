# Codebook gán nhãn Gold Set — VoC Pipeline (MOBI-Qual)

> Đây là **hướng dẫn gán nhãn** cho web labeling. Mọi lớp nhãn được thiết kế để khớp 1:1 với 8 bước của pipeline trong `chon_mo_hinh_pipeline_VoC.pdf`, giúp đào tạo/đánh giá từng mô hình nhỏ riêng biệt.

---

## 0. Đơn vị phân tích

- **Cấp review (review-level)** → cho các bước 1–5: tách ý kiến, sentiment, issue/category, severity, evidence.
- **Cấp case (case-level)** → cho các bước 6–8: insight, recommendation, verifier. Một "case" = một provider trong một khoảng thời gian (không phải một review).

Một review có thể chứa **nhiều opinion unit**, mỗi unit có riêng sentiment / issue / severity / evidence.

---

## 1. Các lớp nhãn cấp review

### Lớp 1 — Opinion-unit extraction (bước 1)

Tách văn bản review thành các **đơn vị ý kiến** liên tiếp, không chồng lấn.

| Trường | Kiểu | Quy tắc |
|---|---|---|
| `unit_id` | string | Ổn định trong review: `u1`, `u2`, … |
| `unit_text` | string | **Phải là chuỗi con nguyên văn** của review gốc (substring). |
| `span` | `[start, end)` | Offset ký tự trong review gốc; máy kiểm tra được bằng code. |

**Quy tắc:**
- Mỗi unit nói về **một chủ đề + một cảm xúc**. Review lẫn khen–chê thì phải tách.
- Không cắt giữa câu trừ khi một câu thật sự chứa 2 ý trái cảm xúc.
- Review rất ngắn (≤ ~15 từ) thường = 1 unit.
- Nếu unit không phải chuỗi con của review gốc → **lỗi, phải sửa**.

### Lớp 2 — Sentiment (bước 2)

Gán cho **từng unit** (không phải cả review).

| Giá trị | Ý nghĩa |
|---|---|
| `positive` | Khen, hài lòng, trải nghiệm tốt |
| `neutral` | Mô tả trung tính, không nghiêng khen/chê |
| `negative` | Chê, phàn nàn, lỗi, thất vọng |

- Ưu tiên phán đoán cảm xúc của **người viết** về chủ đề trong unit.
- Mỉa mai (sarcasm): gán theo nghĩa thực tế người đọc hiểu, ghi chú nếu mơ hồ.
- Câu hỗn hợp đã được tách ở lớp 1 → ít xảy ra ở mức unit.

### Lớp 3 — Issue present + Category (bước 3)

Hai giai đoạn (khớp thiết kế "issue present trước, category sau" trong PDF):

**3a. `issue_present`** — binary:

| Giá trị | Ý nghĩa |
|---|---|
| `yes` | Unit nêu **vấn đề / điểm cần cải thiện** của dịch vụ |
| `no` | Unit chỉ khen / mô tả trung tính, không nêu vấn đề |

**3b. `category`** — multi-label từ **11 macro quality determinant MOBI-Qual + `other`** (xem mục 2). Một unit có thể gán nhiều nhãn nếu chạm nhiều determinant. Nếu `issue_present = no` → `category` để trống.

### Lớp 4 — Severity (bước 4)

Gán cho **mỗi issue** (mỗi cặp unit–category).

| Giá trị | Định nghĩa thực hành |
|---|---|
| `low` | Bất tiện nhỏ, không cản trở dùng dịch vụ |
| `medium` | Ảnh hưởng rõ tới trải nghiệm, gây mất tiền/thời gian vừa phải |
| `high` | An toàn, pháp lý, bị trừ tiền sai, không dùng được dịch vụ, nguy cơ tai nạn |

**Neo tham chiếu (từ PDF):** bị trừ tiền sai, vấn đề an toàn → thường `high`. Nếu tập mẫu quá ít, được phép gộp `low+medium` thành 2 mức và ghi rõ trong báo cáo.

### Lớp 5 — Evidence extraction (bước 5)

Với mỗi issue, chọn **đoạn văn nguyên văn** trong review chứng minh nhãn.

| Trường | Kiểu | Quy tắc |
|---|---|---|
| `evidence_text` | string | **Chuỗi con nguyên văn** của review gốc; không diễn giải lại |
| `evidence_span` | `[start, end)` | Offset ký tự, máy kiểm tra substring |
| `evidence_for` | ref | unit_id + category mà evidence hỗ trợ |

- Không chọn đoạn quá dài / quá chung. Đoạn phải **trực tiếp** chứng minh category + severity.
- Nếu không có đoạn nào hỗ trợ → trả `null` (mô hình sẽ bị chấm `unsupported`).

---

## 2. Codebook category — 11 MOBI-Qual determinants

Danh sách chuẩn (đóng băng cho mọi mode). Nhãn con theo mode chỉ để tra cứu khi phân loại, **khi xuất dữ liệu dùng 11 macro + `other`**.

| # | Macro determinant | Car sharing | Bike sharing | E-scooter sharing |
|---|---|---|---|---|
| 1 | `customer_service` | Customer service (physical office), responsiveness, courtesy | Customer service | Customer service, responsiveness |
| 2 | `app_reliability` | App reliability | App bugs, notification system, map features, app reliability | App reliability, app download issues, app bugs |
| 3 | `charges_fees` | Charges & fees, use rates | Use rates, charges & fees, membership | Passes/programs, use rates, charging policy, use-rate issues |
| 4 | `vehicle_conditions` | Car condition | Battery issues, bike condition | Recharging mode, scooter condition |
| 5 | `sharing_benefits` | Convenience, efficacy, sharing benefits, intermodal | Short-distance commuting, sightseeing, economic convenience, alternative-transport comparison | Convenience, experience pleasantness, riding experience, alternative-transport comparison |
| 6 | `physical_accessibility` | Car availability, car proximity | Bike/dock availability, docks proximity | Scooter location |
| 7 | `parking_area` | Parking area | Use areas | Use & parking areas |
| 8 | `safety` | Accident & damages | Safety | Speed limits/management, safety |
| 9 | `ease_of_use` | End-trip issues, car start-up issues | Ease of use, unlock issues | Ease of use, start-up/scan issues |
| 10 | `digital_accessibility` | Registration process, car reservation | Registration/login issues | Licence validation, phone login issues |
| 11 | `payments` | Billing & membership | Payment | Payment |
| 12 | `other` | — | — | — |

---

## 3. Các lớp nhãn cấp case (bước 6–8)

Đầu vào không phải review thô mà là **bảng tổng hợp có cấu trúc** (số lượng theo category × severity, tỷ lệ, xu hướng theo thời gian, 3–5 evidence snippet kèm review ID) do code tính sẵn.

### Lớp 6 — Insight (top 2)
Mỗi insight bắt buộc kèm `review_id` làm bằng chứng. Trường: `insight_text`, `supporting_review_ids[]`, `category`.

### Lớp 7 — Recommendation (top 2)
Template cố định: `action` (hành động), `where` (làm ở đâu), `who` (cho ai), `why` (vì sao + evidence), `risk` (rủi ro). Trường: `priority` (`high/medium/low`), `actionability`, `feasibility`, `risk`.

### Lớp 8 — Verifier
Với từng claim trong insight/recommendation: `supported` / `partial` / `unsupported` + `reason` ngắn.

---

## 4. Chỉ số đánh giá mỗi lớp (để tính IAA & chấm mô hình)

| Lớp | Chỉ số |
|---|---|
| 1 Units | Tỷ lệ unit đúng nguyên văn (substring match), token-F1 span |
| 2 Sentiment | Macro-F1 (xem riêng F1 lớp `neutral`) |
| 3 Category | Micro-F1 + Macro-F1 (multi-label), exact/Jaccard |
| 4 Severity | Weighted kappa (quadratic), weighted F1 |
| 5 Evidence | Token-F1 span, support rate, tỷ lệ span nguyên văn |
| 6–8 Case-level | Rubric human judge: supported-insight rate, unsupported-claim rate, actionability/feasibility/risk |

> **Trần chất lượng:** độ đồng thuận giữa 2 annotator là trần thực tế — mô hình không được kỳ vọng vượt trần đó (nhất là severity).

---

## 5. Phụ lục — Ví dụ gán nhãn mẫu (tham khảo cho annotator)

### 5.1 Ví dụ cấp review — `BIKE-00023` (BayWheels, Bike sharing, Docked)

**Nguyên văn (247 ký tự):**
> the app is really good and works in real time. However the bikes themselves can be very hit or miss. I have had bike pedals fall off mid ride, bent wheel rims, broken gears, etc. The good news is there are plenty of stations to exchange your bike.

**Lớp 1 — Tách 3 unit:**

| unit_id | unit_text | span |
|---|---|---|
| u1 | `the app is really good and works in real time.` | [0, 46) |
| u2 | `However the bikes themselves can be very hit or miss. I have had bike pedals fall off mid ride, bent wheel rims, broken gears, etc.` | [46, 178) |
| u3 | `The good news is there are plenty of stations to exchange your bike.` | [178, 247) |

> **Vì sao gộp 2 câu vào u2?** Cùng một chủ đề (tình trạng xe) + một cảm xúc (chê). Người khác có thể tách thành 2 unit — đây là chỗ adjudicator hòa giải.

**Lớp 2 — Sentiment:**

| unit | sentiment |
|---|---|
| u1 | `positive` |
| u2 | `negative` |
| u3 | `positive` |

**Lớp 3 — Issue present + Category:**

| unit | issue_present | category |
|---|---|---|
| u1 | `no` | — |
| u2 | `yes` | `vehicle_conditions` |
| u3 | `no` | — |

**Lớp 4 — Severity:**

| unit | severity | Lý do |
|---|---|---|
| u2 | `high` | "pedals fall off **mid ride**" → nguy cơ an toàn (neo: an toàn → high) |

**Lớp 5 — Evidence:**

| unit | evidence_text | evidence_span |
|---|---|---|
| u2 | `I have had bike pedals fall off mid ride, bent wheel rims, broken gears, etc.` | [100, 178) |

### 5.2 Ví dụ cấp case — `LIME_BIKE_2021Q3` (Lime, Bike sharing, 07–08/2021)

**Bảng tổng hợp (code tính sẵn từ nhãn review-level):**

| Category | Số issue | High | Medium | Low |
|---|---|---|---|---|
| app_reliability | 4 | 2 | 2 | 0 |
| charges_fees | 3 | 2 | 1 | 0 |
| customer_service | 3 | 1 | 2 | 0 |
| digital_accessibility | 2 | 0 | 2 | 0 |
| vehicle_conditions | 1 | 1 | 0 | 0 |
| parking_area | 1 | 0 | 1 | 0 |
| **Tổng** | **14** | 6 | 8 | 0 |

**Lớp 6 — Insight (top 2):**
- **Insight 1:** Nhóm lỗi app + xác minh danh tính chiếm 6/14 vấn đề (cao nhất): bản đồ sai khu vực cấm đi/đỗ, quy trình xác minh hay báo lỗi → chặn đầu chuyến đi. `categories: app_reliability, digital_accessibility` · `supporting: BIKE-02708, BIKE-02709, BIKE-02710`
- **Insight 2:** Phí bị thu sai lặp lại (unlock fee dù có gói prime; phí phụ "for no reason") + CS trả lời "canned" → xói mòn lòng tin. `categories: charges_fees, customer_service` · `supporting: BIKE-02706, BIKE-02715, BIKE-02709`

**Lớp 7 — Recommendation (top 2, template 5 phần):**
- **Rec 1 (`high`):** action = tự động hoàn unlock fee cho gói prime + kiểm tra chéo phí phụ · where = hệ thống thanh toán + app · who = kỹ thuật + CS · why = `BIKE-02706`, `BIKE-02715` · risk = lỗ hổng lạm dụng gói nếu không truy ra gốc phí.
- **Rec 2 (`medium`):** action = cập nhật map no-park/no-ride real-time + đơn giản hóa xác minh danh tính · where = app (map + onboarding) · who = đội sản phẩm · why = `BIKE-02708`, `BIKE-02709`, `BIKE-02710` · risk = vướng quy định địa phương về độ tuổi/giấy phép.

**Lớp 8 — Verifier (mỗi claim một trong 3 mức):**

| Claim | Kết quả | Lý do |
|---|---|---|
| "Nhóm lỗi app + xác minh chiếm 6/14" | `supported` | khớp bảng tổng hợp |
| "Bản đồ sai khu vực cấm đi/đỗ" | `supported` | `BIKE-02710` |
| "Tự động hoàn unlock fee cho gói prime" | `partial` | vấn đề có bằng chứng, nhưng *giải pháp* là đề xuất — data không chứng minh khả thi |
| "Điều này khiến Lime mất X% khách hàng" | `unsupported` | dataset không có outcome thực tế (churn) → không claim tác động kinh doanh |
