# Checklist thực nghiệm: chi phí xây đồ thị SciMKG

Mục tiêu: đo chi phí xây đồ thị trên một bài học, kiểm tra chất lượng tương ứng và ước lượng khi mở rộng thành đồ thị chung. SciMKG dùng mô hình có sẵn ở chế độ suy luận; không huấn luyện LLM mới.

Các mục dưới đây là kế hoạch, chưa phải kết quả thực nghiệm.

## 1. Chuẩn bị

- [ ] Kiểm tra một mẫu nhỏ của tác giả trước, sau đó một bài tiếng Việt; ghi rõ nếu chỉ chạy vài trích đoạn.
- [ ] Ghi số đoạn văn bản, ảnh, phút video và tài nguyên còn thiếu. Tách chi phí chuẩn bị dữ liệu khỏi chi phí chạy trên dữ liệu đã chuẩn bị.
- [ ] Chốt mô hình, số vòng kiểm chứng, ngưỡng tích hợp, cờ ConceptNet/Wikipedia và ngân sách chạy.

## 2. Ghi chi phí từng bước

- [ ] Với mỗi lời gọi: lưu bước xử lý, mô hình thực tế, token đầu vào/đầu ra, thời gian, trạng thái và lượt gọi lại; ghi riêng kết quả lấy từ bộ nhớ đệm.
- [ ] Tổng hợp riêng tiền xử lý, EVIA (E/V/I/A), tạo giải thích, căn chỉnh ảnh, TTS và xuất JSON/RDF. Bước chạy cục bộ vẫn ghi thời gian hoặc chi phí máy.
- [ ] Tính tiền theo bảng giá của đúng nhà cung cấp, phiên bản và ngày chạy; tính riêng ảnh, âm thanh hoặc token được tính giá khác nếu có. Không suy tiền từ số lượt gọi đơn thuần.
- [ ] Phân biệt tiền API thực trả, tiền API ước tính và phí thuê bao. Pilot dùng Codex thuê bao không phải phép đo tiền API thực trả; mục thiếu số liệu ghi “chưa đo”.

| Bước | Lượt gọi mới / gọi lại | Token hoặc đơn vị dịch vụ | Thời gian | Chi phí và căn cứ |
|---|---|---|---|---|
| Tiền xử lý | — | — | — | — |
| EVIA: E / V / I / A | — | — | — | — |
| Tạo giải thích | — | — | — | — |
| Căn chỉnh ảnh | — | — | — | — |
| Tạo âm thanh | — | — | — | — |
| Xuất JSON/RDF | — | — | — | — |

## 3. Chi phí có tương xứng với chất lượng?

- [ ] Chuẩn bị nhãn đánh giá trước khi xem dự đoán; tính precision/recall/F1 khi nhãn đủ tin cậy. Nội dung chưa có người đủ chuyên môn duyệt ghi “chưa chấm”.
- [ ] Kiểm tra một số liên kết khái niệm–ảnh/video và giải thích; đọc lại JSON/RDF để phát hiện liên kết thiếu hoặc sai định danh.
- [ ] So sánh cấu hình đầy đủ đã chọn với cấu hình tắt verification và cấu hình tắt augmentation. Giữ cùng dữ liệu, mô hình và thiết lập ở các bước chung; ghi riêng cờ nguồn ngoài và mọi thay đổi khác.
- [ ] Báo cả chất lượng, chi phí và thời gian của từng cấu hình; phân biệt lượt suy luận mới với phép tính lại từ phản hồi đã lưu.

## 4. Ước lượng đồ thị lớn và khả năng chạy lại

- [ ] Báo chi phí mỗi bài học và mỗi khái niệm được giữ; thêm chi phí mỗi khái niệm đúng khi có nhãn đáng tin cậy.
- [ ] Ước lượng sơ bộ: chi phí chuẩn bị chung + số bài × chi phí trung bình mỗi bài. Ghi giả định về độ dài, số ảnh, khái niệm trùng và khả năng tái sử dụng kết quả; một mẫu chỉ đủ thăm dò, không đại diện toàn bộ tập.
- [ ] Lưu phiên bản mã, dữ liệu, prompt, tham số, tên/phiên bản mô hình, ngày chạy và phản hồi trung gian để đối chiếu.
- [ ] Ghi rõ mô hình thay thế nếu API gốc không còn dùng được. Bản cập nhật mô hình có thể đổi đầu ra; không coi việc chạy bằng mô hình khác là tái lập chính xác cấu hình tác giả.

Đầu ra cần có: bảng chi phí từng bước, bảng chất lượng–chi phí giữa các cấu hình và ước lượng mở rộng kèm giả định.
