# Checklist

## Problem

Theo đánh giá của nhóm, các bước xử lý ngữ nghĩa trong SciMKG phụ thuộc nhiều vào LLM có sẵn: trích xuất, kiểm chứng, bổ sung khái niệm và căn chỉnh ảnh. Phép tích hợp điểm, ghép mốc video và lưu đồ thị được xử lý bằng mã.

**Câu hỏi chính: Để xây dựng một đồ thị tri thức chung (global graph) như SciMKG, cần tốn bao nhiêu chi phí API?** Chi phí này cần được xem cùng chất lượng đồ thị thu được.

## Experiments

### Chuẩn bị chung cho Ex01 và Ex02

- [x] Chọn và chuẩn bị sáu bài có văn bản đầu vào trong `RawData.zip` và nhãn công bố trong `Groundtruth.zip` của tác giả ([Zenodo](https://zenodo.org/records/19691725)), mỗi môn hai bài. Ex01 dùng `nervous-system`; Ex02 dùng cả sáu bài, gồm bài Ex01. Dữ liệu ở `data/MOOC/`; nguồn và hash trong [manifest](data/MOOC/manifest.json), danh sách/phạm vi trong [docs/MOOC.md](docs/MOOC.md).
- [x] Đối chiếu đúng bài và cố định nhãn công bố: 75 đoạn và 188 nhãn theo bài; giữ nguyên tệp gốc, kiểm tra CRC và SHA-256. Dùng đầy đủ văn bản công bố của từng bài để chấm với nhãn riêng trong `evaluation`; đầu vào mô hình chỉ ở `inputs`. Hai bài Vật lý bị cắt dở trong nguồn đã được thay trước khi chạy mô hình; xem [đối chiếu nguồn](docs/MOOC.md#đối-chiếu-văn-bản-và-nhãn).

### Ex01: Giải phẫu chi phí một bài học

**Mục đích:** đo một bài học đi từ văn bản đến đồ thị tốn bao nhiêu lời gọi, token và thời gian.
Rồi quy ra tiền theo giá API công khai.
Không đánh giá chất lượng.

**Chạy:** bài `nervous-system`, đủ pipeline, `gpt-6-luna` (effort low), 5 vòng, ngưỡng 0,7, một lượt duy nhất.

**Đầu ra sau khi chạy:**
- Bảng token, thời gian và tiền theo bước và bước con (E, V feedback, V refinement, I, A, giải thích, ảnh lần 1, 2, 3).
- Tổng chi phí kiểu API (một con số), kèm số CLI đo được làm tham chiếu phụ.
- Đơn giá mỗi đơn vị (đoạn, ảnh, khái niệm).
- Quy đổi sang các mô hình bài báo dùng (GPT-4o, DeepSeek-V3, Gemini-1.5-Flash) theo cấu hình của mã tác giả (mỗi bước một mô hình, V gồm ba mô hình), và sang các mô hình hiện hành (Luna, Terra, Sol).
- Đồ thị của bài (JSON, RDF, giải thích, WAV) và dashboard W&B công khai.

- [ ] Chạy lại Ex01 theo thiết kế trên và đưa số đo vào báo cáo.

### Ex02: Hiệu quả của từng bước

**Tiêu chí chọn cấu hình ablation:** một cấu hình chỉ được đưa vào Ex02 khi thỏa cả bốn điều kiện.
1. Đổi một yếu tố tốn nhiều chi phí ở Ex01, để kết quả trả lời được "tốn bao nhiêu để mua chất lượng".
2. Chấm được bằng dữ liệu hiện có (hiện chỉ có nhãn ở mức khái niệm).
3. Bài báo có mốc để so, dù chỉ so được chiều thay đổi.
4. Kết quả có thể đổi một quyết định, ví dụ có nên giữ 5 vòng kiểm chứng khi mở rộng.

- [x] Trên từng bài trong sáu bài đã cố định, so sánh ba cấu hình: đầy đủ (5 vòng), 1 vòng kiểm chứng (thay cho tắt augmentation), tắt verification (18 lượt chạy; `full` trên `nervous-system` dùng lại lượt Ex01). Khi tắt verification, dùng ứng viên trích xuất trực tiếp; khi chỉ 1 vòng, giữ ngưỡng 0,7 và ghi số vòng vào cấu hình. Mã và cách chạy: [docs/EX02.md](docs/EX02.md).
  - [x] Mã Ex02 dùng lại hàm E/V/I/A của Ex01; chạy thử offline đủ ba cấu hình bằng client giả.
  - [x] Lượt thử thật: `amphibian-reproduction`, tắt verification (37 lời gọi, có run W&B).
  - [x] 16 lượt còn lại (`scripts/experiments/ex-02/run_all.sh`).
  - Đã cân nhắc nhưng không làm (14/10/2026): thêm Haiku vào V, lặp lại mỗi cấu hình, 3 vòng V, quét ngưỡng.
    Mỗi ô chỉ có một lần chạy, nên chênh lệch giữa cấu hình gồm cả dao động giữa các lần gọi E; báo cáo cần ghi rõ giới hạn này.
- [x] Giữ cùng dữ liệu, mô hình và tham số ở các bước chung; đo chất lượng, chi phí và thời gian cho mỗi cấu hình.
- [x] Gộp và loại trùng khái niệm sau Integration, trước Augmentation, theo bài học; tính precision/recall/F1 với nhãn của đúng bài. Báo cáo từng bài và trung bình cộng từng chỉ số trên sáu bài. Phép chấm này đánh giá trích xuất–kiểm chứng–tích hợp.
- [x] Với Augmentation, ghi chi phí và số khái niệm bổ sung. Chỉ chấm chất lượng bổ sung hoặc căn chỉnh ảnh/video khi có nhãn chuẩn tương ứng; mẫu hiện đã kiểm tra chưa có các nhãn đó.

**Dữ liệu đánh giá:** dùng nhãn chuẩn công bố của tác giả; Ex02 không dùng dữ liệu tiếng Việt hoặc nhãn do nhóm/LLM tự tạo. Đầu ra `_Intergrationner` và đồ thị tác giả sinh ra là kết quả tham chiếu, không tự trở thành nhãn chuẩn.

**Đầu ra:** bảng precision/recall/F1–chi phí cho phần có nhãn chuẩn; ghi rõ chất lượng phần nào chưa đo được.

### Sau Ex01–Ex02: Ước lượng khi mở rộng

- [ ] Từ cấu hình đã đánh giá, ước lượng chi phí cho nhiều bài; xét độ dài bài, số ảnh, khái niệm trùng và kết quả có thể tái sử dụng.
- [ ] Ghi giả định và phạm vi ước lượng. Ex01 dùng một bài, Ex02 dùng sáu bài; đây vẫn là mẫu nhỏ, cần thêm mẫu đại diện để kết luận chi phí toàn tập.

### Ex03: Đồ thị có giúp tác vụ hạ nguồn không

**Mục đích:** bài báo nói đồ thị phục vụ hỏi đáp, sinh câu hỏi và trợ lý học tập, nhưng không đo tác vụ nào.
Ex03 kiểm tra điều đó trên chính sáu bài của Ex02.
Thay cho Ex03 cũ (bài học tiếng Việt), quyết định ngày 14/10/2026.

- [x] Kiểm tra nguồn câu hỏi trắc nghiệm: C-Eval, CMMLU, E-EVAL, M3Exam cộng lại chỉ có 1 đến 38 câu có đáp án khớp từ khóa mỗi bài, nên bỏ hướng hỏi đáp.
- [x] Chọn tác vụ tìm đúng đoạn bài giảng: truy vấn là câu trong bài (nguyên văn) và câu hỏi viết lại; đáp án là mốc thời gian có sẵn. Thiết kế: [docs/EX03.md](docs/EX03.md).
- [x] Mã `experiments/ex03/`, chạy được trên truy vấn nguyên văn với các lượt Ex02 đã xong.
- [x] Tạo 309 câu hỏi viết lại.
- [x] Bảng cuối khi đủ 18 lượt Ex02: so `full`/`one-round`/`no-verification`, cách gắn đoạn đầu tiên với mọi đoạn, có và không có A, BM25 và ngẫu nhiên; một run W&B tổng hợp ([ex03-gpt-6-luna](https://wandb.ai/nhinbm-hcmus/SciMKG/runs/krpbt4zl)).

## Công khai kết quả bằng Weights & Biases

- [ ] Mỗi cấu hình có một lượt chạy W&B, lưu cấu hình, chi phí, thời gian, chỉ số chất lượng và bảng nhãn–dự đoán; đính kèm JSON/RDF và nguồn dữ liệu để đối chiếu.
- [ ] Ex01 chạy lại: run `<mô hình>-<bài>` trong dự án Public, dashboard bốn mục xem được công khai (kiểm tra bằng cửa sổ ẩn danh).

Tham khảo: [ghi dữ liệu và kết quả](https://docs.wandb.ai/guides/track/log/), [quyền xem dự án công khai](https://docs.wandb.ai/guides/hosting/iam/access-management/restricted-projects/).
