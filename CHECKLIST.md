# Checklist

## Problem

Theo đánh giá của nhóm, các bước xử lý ngữ nghĩa trong SciMKG phụ thuộc nhiều vào LLM có sẵn: trích xuất, kiểm chứng, bổ sung khái niệm và căn chỉnh ảnh. Phép tích hợp điểm, ghép mốc video và lưu đồ thị được xử lý bằng mã.

**Câu hỏi chính: Để xây dựng một đồ thị tri thức chung (global graph) như SciMKG, cần tốn bao nhiêu chi phí API?** Chi phí này cần được xem cùng chất lượng đồ thị thu được.

## Experiments

### Ex01: One lesson — Chi phí một bài học

- [ ] Chạy một bài học mẫu nhỏ của tác giả; ghi số đoạn văn bản, ảnh và thời lượng video. Nếu chỉ có trích đoạn, báo chi phí đúng phạm vi đó.
- [ ] Đo số lượt gọi, token đầu vào/đầu ra và thời gian; tách EVIA (E/V/I/A), tạo giải thích, căn chỉnh ảnh và tạo âm thanh. Chi phí tiền xử lý ghi riêng.
- [ ] Ghi cả lượt gọi lại và kết quả lấy từ bộ nhớ đệm; lưu mô hình/phiên bản, prompt, số vòng, ngưỡng, cờ nguồn ngoài, phiên bản mã và ngày chạy.
- [ ] Tính tiền theo đơn vị dịch vụ và bảng giá ngày chạy; phân biệt tiền API thực trả với tiền ước tính khi dùng thuê bao.

**Đầu ra:** bảng chi phí từng bước và tổng chi phí cho bài học.

### Ex02: Hiệu quả của từng bước

- [ ] So sánh ba cấu hình: đầy đủ đã chọn, tắt verification, tắt augmentation. Khi tắt verification, dùng ứng viên trích xuất trực tiếp; khi tắt augmentation, ghi rõ cờ ConceptNet/Wikipedia đã tắt.
- [ ] Giữ cùng dữ liệu, mô hình và tham số ở các bước chung; đo chất lượng, chi phí và thời gian cho mỗi cấu hình.

**Nhãn để đo chất lượng:**

- **Trích xuất:** danh sách khái niệm đúng gắn với từng đoạn văn bản; tính precision/recall/F1. Dùng nhãn `Groundtruth` của tác giả cho đúng bài và phạm vi mẫu, sau khi đối chiếu.
- **Ảnh/video:** người duyệt đánh dấu cặp khái niệm–tài nguyên có liên quan hay không, kèm căn cứ từ hình hoặc nội dung đoạn video; báo tỷ lệ liên kết đúng trong mẫu đã duyệt. Nhãn trích xuất chưa đủ để chấm phần này.
- **Augmentation:** chấm riêng khái niệm mới về tính đúng và liên quan đến bài, cùng độ chính xác của giải thích; một khái niệm không có trong nhãn trích xuất chưa chắc là sai.

- [ ] Chốt nhãn trích xuất trước khi xem dự đoán; dùng cùng tiêu chí chấm cho mọi cấu hình. Nhãn do LLM gợi ý cần người hiểu nội dung duyệt; phần chưa đủ chuyên môn xác minh ghi “chưa chấm”.

**Đầu ra:** bảng chất lượng–chi phí và ví dụ cho thấy verification/augmentation có ích hoặc gây lỗi.

### Sau Ex01–Ex02: Ước lượng khi mở rộng

- [ ] Từ cấu hình đã đánh giá, ước lượng chi phí cho nhiều bài; xét độ dài bài, số ảnh, khái niệm trùng và kết quả có thể tái sử dụng.
- [ ] Ghi giả định và phạm vi ước lượng. Một bài chỉ cho ước lượng thăm dò; cần thêm mẫu để kết luận chi phí toàn tập.

### Ex03 (tùy chọn): Một số bài học tiếng Việt

- [ ] Sau mẫu tác giả, thử vài video bài học tiếng Việt, ưu tiên lịch sử (ví dụ 1–3 bài), có phụ đề/văn bản và ảnh hoặc slide nếu có.
- [ ] Điều chỉnh prompt, tiêu chí chọn khái niệm và nguồn ngoài theo tiếng Việt/lịch sử; ghi thay đổi so với cấu hình SciMKG.
- [ ] Người hiểu bài học chuẩn bị nhãn khái niệm theo đoạn và duyệt liên kết tài nguyên, giải thích; sau đó đo chất lượng và chi phí như Ex01–Ex02.

**Đầu ra:** kết luận khả thi trên mẫu nhỏ. Lịch sử đồng thời thay đổi ngôn ngữ và lĩnh vực so với khoa học tự nhiên của SciMKG, nên cần ghi rõ hai thay đổi này.

## Công khai kết quả bằng Weights & Biases

- [ ] Mỗi cấu hình có một lượt chạy W&B, lưu cấu hình, chi phí, thời gian, chỉ số chất lượng và bảng nhãn–dự đoán; đính kèm JSON/RDF và nguồn dữ liệu để đối chiếu.
- [ ] Đồng bộ kết quả lên dự án đặt chế độ **Public**, kiểm tra link người ngoài xem được và dẫn link trong báo cáo. W&B có thể ghi nhận thực nghiệm suy luận; nhãn và chỉ số cần do nhóm chuẩn bị/tính.

Tham khảo: [ghi dữ liệu và kết quả](https://docs.wandb.ai/guides/track/log/), [quyền xem dự án công khai](https://docs.wandb.ai/guides/hosting/iam/access-management/restricted-projects/).
