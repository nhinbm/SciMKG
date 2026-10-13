# Checklist

## Problem

Theo đánh giá của nhóm, các bước xử lý ngữ nghĩa trong SciMKG phụ thuộc nhiều vào LLM có sẵn: trích xuất, kiểm chứng, bổ sung khái niệm và căn chỉnh ảnh. Phép tích hợp điểm, ghép mốc video và lưu đồ thị được xử lý bằng mã.

**Câu hỏi chính: Để xây dựng một đồ thị tri thức chung (global graph) như SciMKG, cần tốn bao nhiêu chi phí API?** Chi phí này cần được xem cùng chất lượng đồ thị thu được.

## Experiments

### Chuẩn bị chung cho Ex01 và Ex02

- [x] Chọn và chuẩn bị sáu bài có văn bản đầu vào trong `RawData.zip` và nhãn công bố trong `Groundtruth.zip` của tác giả ([Zenodo](https://zenodo.org/records/19691725)), mỗi môn hai bài. Ex01 dùng `nervous-system`; Ex02 dùng cả sáu bài, gồm bài Ex01. Dữ liệu ở `data/MOOC/`; nguồn và hash trong [manifest](data/MOOC/manifest.json), danh sách/phạm vi trong [docs/MOOC.md](docs/MOOC.md).
- [x] Đối chiếu đúng bài và cố định nhãn công bố: 75 đoạn và 188 nhãn theo bài; giữ nguyên tệp gốc, kiểm tra CRC và SHA-256. Dùng đầy đủ văn bản công bố của từng bài để chấm với nhãn riêng trong `evaluation`; đầu vào mô hình chỉ ở `inputs`. Hai bài Vật lý bị cắt dở trong nguồn đã được thay trước khi chạy mô hình; xem [đối chiếu nguồn](docs/MOOC.md#đối-chiếu-văn-bản-và-nhãn).

### Ex01: One lesson — Chi phí một bài học

- [ ] Chạy đầy đủ bài mẫu chung đã chọn; ghi số đoạn văn bản, ảnh, thời lượng video và tài nguyên còn thiếu.
- [ ] Đo số lượt gọi, token đầu vào/đầu ra và thời gian; tách EVIA (E/V/I/A), tạo giải thích, căn chỉnh ảnh và tạo âm thanh. Chi phí tiền xử lý ghi riêng.
- [ ] Ghi cả lượt gọi lại và kết quả lấy từ bộ nhớ đệm; lưu mô hình/phiên bản, prompt, số vòng, ngưỡng, cờ nguồn ngoài, phiên bản mã và ngày chạy.
- [ ] Tính tiền theo đơn vị dịch vụ và bảng giá ngày chạy; phân biệt tiền API thực trả với tiền ước tính khi dùng thuê bao.

**Đầu ra:** bảng chi phí từng bước và tổng chi phí cho bài học.

### Ex02: Hiệu quả của từng bước

- [ ] Trên từng bài trong sáu bài đã cố định, so sánh ba cấu hình: đầy đủ đã chọn, tắt verification, tắt augmentation (18 lượt chạy). Khi tắt verification, dùng ứng viên trích xuất trực tiếp; khi tắt augmentation, ghi rõ cờ ConceptNet/Wikipedia đã tắt.
- [ ] Giữ cùng dữ liệu, mô hình và tham số ở các bước chung; đo chất lượng, chi phí và thời gian cho mỗi cấu hình.
- [ ] Gộp và loại trùng khái niệm sau Integration, trước Augmentation, theo bài học; tính precision/recall/F1 với nhãn của đúng bài. Báo cáo từng bài và trung bình cộng từng chỉ số trên sáu bài. Phép chấm này đánh giá trích xuất–kiểm chứng–tích hợp.
- [ ] Với Augmentation, ghi chi phí và số khái niệm bổ sung. Chỉ chấm chất lượng bổ sung hoặc căn chỉnh ảnh/video khi có nhãn chuẩn tương ứng; mẫu hiện đã kiểm tra chưa có các nhãn đó.

**Dữ liệu đánh giá:** dùng nhãn chuẩn công bố của tác giả; Ex02 không dùng dữ liệu tiếng Việt hoặc nhãn do nhóm/LLM tự tạo. Đầu ra `_Intergrationner` và đồ thị tác giả sinh ra là kết quả tham chiếu, không tự trở thành nhãn chuẩn.

**Đầu ra:** bảng precision/recall/F1–chi phí cho phần có nhãn chuẩn; ghi rõ chất lượng phần nào chưa đo được.

### Sau Ex01–Ex02: Ước lượng khi mở rộng

- [ ] Từ cấu hình đã đánh giá, ước lượng chi phí cho nhiều bài; xét độ dài bài, số ảnh, khái niệm trùng và kết quả có thể tái sử dụng.
- [ ] Ghi giả định và phạm vi ước lượng. Ex01 dùng một bài, Ex02 dùng sáu bài; đây vẫn là mẫu nhỏ, cần thêm mẫu đại diện để kết luận chi phí toàn tập.

### Ex03 (tùy chọn): Một số bài học tiếng Việt

- [ ] Sau mẫu tác giả, thử vài video bài học tiếng Việt, ưu tiên lịch sử (ví dụ 1–3 bài), có phụ đề/văn bản và ảnh hoặc slide nếu có.
- [ ] Điều chỉnh prompt, tiêu chí chọn khái niệm và nguồn ngoài theo tiếng Việt/lịch sử; ghi thay đổi so với cấu hình SciMKG.
- [ ] Người hiểu bài học chuẩn bị nhãn khái niệm theo đoạn và duyệt liên kết tài nguyên, giải thích; sau đó đo chất lượng và chi phí như Ex01–Ex02.

**Đầu ra:** kết luận khả thi trên mẫu nhỏ. Lịch sử đồng thời thay đổi ngôn ngữ và lĩnh vực so với khoa học tự nhiên của SciMKG, nên cần ghi rõ hai thay đổi này.

## Công khai kết quả bằng Weights & Biases

- [ ] Mỗi cấu hình có một lượt chạy W&B, lưu cấu hình, chi phí, thời gian, chỉ số chất lượng và bảng nhãn–dự đoán; đính kèm JSON/RDF và nguồn dữ liệu để đối chiếu.
- [ ] Đồng bộ kết quả lên dự án đặt chế độ **Public**, kiểm tra link người ngoài xem được và dẫn link trong báo cáo. W&B có thể ghi nhận thực nghiệm suy luận; nhãn và chỉ số cần do nhóm chuẩn bị/tính.

Tham khảo: [ghi dữ liệu và kết quả](https://docs.wandb.ai/guides/track/log/), [quyền xem dự án công khai](https://docs.wandb.ai/guides/hosting/iam/access-management/restricted-projects/).
