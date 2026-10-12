# Findings

## F1: Điểm kiến thức cần dữ liệu chuẩn bị sẵn

- Mã đọc tên điểm kiến thức từ JSON và ghép theo tên; tên không được hardcode trong mã.
- Bài báo nói nguồn là chuẩn chương trình và đề cương MOOC, nhưng quy trình tạo JSON đầu vào và gán khái niệm vào điểm kiến thức chưa được mô tả đầy đủ.

Nguồn: bài báo, mục *Knowledge Organization*, tr. 15470; [GeneratorKnowledgeJson.py](../SciMKGConstruction/GeneratorKnowledgeJson.py), [GeneratorTriples.py](../SciMKGConstruction/GeneratorTriples.py).
