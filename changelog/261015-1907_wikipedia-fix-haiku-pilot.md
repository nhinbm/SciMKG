# Sửa trích Wikipedia, thử nghiệm Haiku và biểu đồ W&B

## Thay đổi

- `experiments/ex01/resources.py`: lấy khối `.mw-parser-output` đầu tiên có đoạn văn thay vì khối đầu tiên của trang.
  Trước đó 23 trong 82 trang tải được cho văn bản rỗng, nên các giải thích đó dùng bản dự phòng của mô hình.
  Tách phần lọc đoạn thành hàm `article_paragraphs`; luật lọc không đổi.
- Chạy lại bước giải thích của Ex01 trên bản sao `runs/pipeline/gpt-6-luna/nervous-system-wikipedia-fix/`: 23 lượt gọi mới, 82 giải thích có nguồn, đồ thị không đổi.
  Không gửi lên W&B; lượt Ex01 gốc giữ nguyên.
- `experiments/ex01/claude_client.py`: client gọi Claude CLI cùng giao diện với `CodexClient`, chỉ dùng đăng nhập thuê bao claude.ai.
- `experiments/ex02/haiku_validation.py`: thử nghiệm phụ, bước V chạy trên `gpt-6-luna` và `claude-haiku-5-5` với hai bài.
  Kết luận ghi trong `docs/EX02.md`: không đưa Haiku vào cấu hình chính.
- `scripts/experiments/publish_charts.py`: thêm biểu đồ cột vào run W&B tổng hợp của Ex02 và Ex03 từ các CSV đã có, không tạo run mới.
- `docs/EX01.md`: điền mục Kết quả, ghi bản sửa Wikipedia và phép kiểm phần ngữ cảnh cố định của CLI.

## Ghi chú

- Không lượt nào trong số này gọi API trả phí.
- Mã Ex02 chính không đổi; thử nghiệm Haiku ghi ra thư mục riêng `runs/experiments/ex-02-validation/`.
