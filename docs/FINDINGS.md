# Findings

## F1: Điểm kiến thức cần dữ liệu chuẩn bị sẵn

- Mã đọc tên điểm kiến thức từ JSON và ghép theo tên; tên không được hardcode trong mã.
- Bài báo nói nguồn là chuẩn chương trình và đề cương MOOC, nhưng quy trình tạo JSON đầu vào và gán khái niệm vào điểm kiến thức chưa được mô tả đầy đủ.

Nguồn: bài báo, mục *Knowledge Organization*, tr. 15470; [GeneratorKnowledgeJson.py](../SciMKGConstruction/GeneratorKnowledgeJson.py), [GeneratorTriples.py](../SciMKGConstruction/GeneratorTriples.py).

## F2: Bước bổ sung ConceptNet không chạy được như mã công bố

> **Trạng thái: ✅ Đã có cách xử lý trong Ex01.**
> Mã tác giả giữ nguyên; Ex01 chỉ thay lời gọi mạng và điền phần còn trống khi chạy.
> Đã kiểm chứng offline với mô hình giả; lượt chạy thật đang theo các bước (xem [EX01.md](EX01.md)).

- Hàm `extract_cell_nouns` có danh sách luật `patterns` rỗng (chỉ có chú thích `# your rules`), nên không bao giờ trả về ứng viên và bước bổ sung không thêm khái niệm nào.
  - ✅ **Đã xử lý:** Ex01 điền luật theo các mẫu câu tiếng Anh lấy từ dump ConceptNet (`surface_rules` trong [conceptnet.py](../experiments/ex01/conceptnet.py)).
    Với luật rỗng của mã công bố, bước bổ sung không gọi mô hình và không thêm khái niệm nào; đây là hệ quả trực tiếp của mã, không cần đo riêng.
- `get_surface_texts` chỉ giữ thuật ngữ tiếng Anh cuối cùng trong vòng lặp; thứ tự này lấy từ một `set`, nên có thể đổi giữa các lần chạy.
  - ✅ **Đã xử lý:** luật đối chiếu với mọi thuật ngữ tiếng Anh đã tra cho khái niệm, nên kết quả không phụ thuộc thứ tự `set` (`LocalConceptNet.english_terms`).
- Mã chỉ gọi `api.conceptnet.io`; ngày 14/10/2026 mọi đường dẫn API đều trả lỗi 502, mã gốc bắt lỗi rồi coi như không có thuật ngữ.
  - ✅ **Đã xử lý:** yêu cầu API được trả lời từ dump công bố `conceptnet-assertions-5.7.0.csv.gz` (ghim SHA-256), cùng dạng JSON và giữ nguyên `surfaceText` (`LocalConceptNet`).
    Lưu ý: dump là bản 5.7, API trước đây phục vụ bản 5.8.
- `imageAnalysis` thử lại vô hạn trong `except:` trần, nên cũng nuốt cả tín hiệu dừng của chương trình.
  - ✅ **Đã xử lý:** Ex01 chỉ lấy prompt từ hàm gốc rồi tự gửi qua client có giới hạn lượt gọi (`image_prompt` trong [author.py](../experiments/ex01/author.py)).
- ⚠️ **Chưa xử lý được:** quan hệ `DerivedFrom` không có `surfaceText` trong dump, nên cách lọc theo câu của tác giả không thấy được quan hệ này.

Nguồn: [ConceptNet.py](../ExtractMultimodalConcepts/ConceptNet.py), [NER.py](../ExtractMultimodalConcepts/NER.py) (`conceptExpand`), [ImageAligment.py](../MultimodalAlignment/ImageAligment.py).
