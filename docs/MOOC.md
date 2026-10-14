# Bộ dữ liệu MOOC cho Ex01 và Ex02

Nguồn: [SciMKG trên Zenodo](https://zenodo.org/records/19691725), giấy phép CC BY 4.0.
Đã chuẩn bị **6 bài, 75 đoạn văn bản và 188 nhãn theo bài** từ `RawData.zip` và `Groundtruth.zip`.

| Mã bài | Môn | Đoạn | Nhãn |
|---|---|---:|---:|
| `nervous-system` | Sinh học | 14 | 30 |
| `amphibian-reproduction` | Sinh học | 7 | 57 |
| `atmospheric-pressure` | Vật lý | 12 | 21 |
| `buoyancy` | Vật lý | 14 | 19 |
| `sulfuric-acid-and-sulfate` | Hóa học | 15 | 13 |
| `proteins` | Hóa học | 13 | 48 |

Ex01 dùng `nervous-system`; Ex02 dùng cả sáu bài × ba cấu hình, tổng cộng 18 lượt dự kiến.

Dữ liệu nằm ở `data/MOOC/<lesson_id>/`: `inputs/lesson.txt` dành cho mô hình;
`evaluation/groundtruth.txt` và `evaluation/gold.json` dành cho chấm theo toàn bài.
Tệp gốc giữ nguyên byte; JSON nhãn có `status: frozen`, chỉ bỏ dòng trắng và khoảng trắng đầu/cuối.
[Manifest](../data/MOOC/manifest.json) ghi nguồn, đường dẫn và CRC/SHA-256 để đối chiếu đúng bản dữ liệu.

Yêu cầu Python ≥ 3.11:

```bash
python3 scripts/preprocessing/prepare_mooc.py
python3 scripts/preprocessing/prepare_mooc.py --check
```

Lệnh đầu tải các thành phần đã chọn nếu chưa có dữ liệu; `--check` chỉ kiểm tra cục bộ.

## Đối chiếu văn bản và nhãn

Hai bài Vật lý ban đầu, Đặc tính của âm thanh và Mắt và kính mắt, bị cắt dở trong nguồn;
đã thay bằng Áp suất khí quyển và Lực đẩy trước khi chạy mô hình.

Ảnh/video/âm thanh/PDF chưa được chuẩn bị. Các mốc văn bản chưa xác nhận thời lượng video gốc;
sáu bài là khảo sát nhỏ. Phạm vi thực nghiệm: [CHECKLIST.md](../CHECKLIST.md).
