# Ex01: một pipeline, một bài, thư mục theo mô hình và bài

## Thay đổi

- Bỏ hai biến thể `current` và `completed`; mọi lượt chạy dùng luật bổ sung ConceptNet đã điền.
  Cache và thư mục kết quả không còn tách theo biến thể.
- Thư mục lượt chạy là `runs/pipeline/<mô hình>/<bài>/`, không còn tên dài theo tham số và không có dấu thời gian.
- Thêm `--until {E,V,A,images,explanations,all}` để dừng đúng ranh giới bước; `evia` là tên gọi tắt của A.
- Mỗi lần chạy ghi một dòng vào `batches.jsonl`, gồm số lời gọi, token CLI, lý do dừng và giờ reset nếu có.
- Hết hạn mức hoặc hết ngân sách của đợt thì thoát với mã 75; lỗi khác vẫn thoát với mã 1.
  Lỗi hết hạn mức được nhận diện qua chuỗi nguyên nhân, vì mã tác giả bọc lại lỗi thành `RuntimeError`.
- Ngân sách đợt (`--max-new-calls`, `--max-run-seconds`) mặc định không giới hạn và đếm ngay trong client.
- Cache LLM và cache web chuyển sang một file JSONL nối thêm mỗi bên; dòng bị cắt dở khi ghi được bỏ qua và tự sửa.
- Không còn file thô theo từng lần thử của Codex; nội dung lỗi nằm trong nhật ký.
- Âm thanh: mỗi khái niệm một WAV trong `audio/`, chỉ mục trong `audio.json`; chạy tiếp không tổng hợp lại âm thanh đã có.
- Sửa tên trường đọc cache-write: CLI báo `cache_write_input_tokens`, mã trước đọc nhầm tên và lưu `None`.
- Bỏ phép quy đổi tiền khỏi runner; tiền theo giá API được tính ở `scripts/experiments/ex-01/analyze.py`.
- Thêm `scripts/experiments/ex-01/analyze.py` (đọc file đã lưu, không gọi mô hình) và `prices.json` (giá có nguồn và trạng thái).
- Bỏ báo cáo W&B Report; dashboard là saved view, và dự án ở chế độ Public.
- Ghim `tiktoken==0.14.0` trong `requirements-ex01.txt`.

## Ghi chú

- `token_report.py` đã bị xóa; phần đưa số lên W&B được thay bằng bảng và khóa summary có tiền tố.
- Preprocessing vẫn dùng một `mooc/lesson.json`; tách theo bài sẽ làm khi bắt đầu Ex02.
