# Ex01: dùng lại mã tác giả cho các bước SciMKG

## Thay đổi

- Bổ sung A gọi `NER.conceptExpand` và `ConceptNet.get_surface_texts` của tác giả.
  `current` giữ luật rỗng; `completed` chỉ điền luật mẫu câu tiếng Anh vào `extract_cell_nouns`.
- API ConceptNet trả lỗi 502, nên yêu cầu API được trả lời từ dump 5.7.0 đã ghim SHA-256, qua chỉ mục SQLite tại `runs/preprocessing/conceptnet/`.
- Ảnh dùng prompt của `ImageAligment.imageAnalysis`, ứng viên là khái niệm E/V/I như `mainImages`.
- Giải thích dùng `NER.expandExplanations`; chỉ thay tra cứu Wikipedia bằng Wikipedia tiếng Trung.
- Xuất đồ thị theo từ vựng `GeneratorTriples.py` và `TriplesToRDF` của `RDF/rdf.py`; `graph.json` thay bằng `triples.json`.
- Gỡ mã thay thế và mã không còn đường gọi: bộ đọc ConceptNet API/browser riêng, `discover_video_candidates`,
  ba lệnh tiền xử lý, `call_budget`, `replay_request`.
- Mã tác giả được thực thi nay nằm trong dấu vân tay mã của lượt; thêm `Wikipedia-API` và `openai` vào `requirements-ex01.txt`.
- `pipeline_protocol` lên 3; lượt 13/10/2026 giữ nguyên, chưa chạy lượt mới.
- Tổ chức lại `runs/`: `preprocessing/{mooc,conceptnet}`, `experiments/ex-01/<tham số>/` và `archived/ex-01/` cho dữ liệu cũ.
  Lượt mặc định đặt tên theo tham số thay cho thời điểm chạy.
- `scripts/` xếp giống `runs/`: `scripts/preprocessing/prepare_mooc.py`, `scripts/preprocessing/prepare_conceptnet.py` (mới) và `scripts/experiments/ex-01/run.py` (thay `scripts/run_ex01.py`).
