# Ex03: tìm đoạn bài giảng bằng đồ thị

## Thay đổi

- Thêm gói `experiments/ex03/` và lệnh `scripts/experiments/ex-03/run.py` với hai lệnh con `queries` và `evaluate`.
- Ex03 thay Ex03 cũ (bài học tiếng Việt); hướng hỏi đáp trắc nghiệm bị loại vì bốn bộ đề công khai không đủ câu đúng chủ đề.
- 309 câu nguồn từ bản ghi sáu bài; câu hỏi viết lại bằng `CodexClient` của Ex01, có cache, nhật ký và mã 75 khi hết hạn mức.
- Chỉ đọc kết quả Ex02 qua `experiments.ex02.summary.folder_for`; không sửa mã hay thư mục lượt chạy của Ex02.
- Truy hồi: chỉ mục khái niệm theo cách gắn của tác giả, theo mọi đoạn có nhắc, và có thêm khái niệm bổ sung; BM25 cặp ký tự và ngẫu nhiên làm mốc.

## Ghi chú

- Prompt viết lại đầu tiên cho câu hỏi chung chung ("今天这节课要讲什么内容？"); bản hiện tại giữ thuật ngữ khoa học và yêu cầu hỏi đúng nội dung câu.
  Câu viết lại bằng prompt cũ không được dùng lại.
