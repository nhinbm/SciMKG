# Bộ dữ liệu MOOC cho Ex01 và Ex02

Đã chuẩn bị ngày 13/10/2026: sáu bài, mỗi môn hai bài, gồm **75 đoạn văn bản**
và **188 nhãn khái niệm theo bài**. Các số này mô tả dữ liệu đầu vào; chưa
chạy mô hình hoặc đo chất lượng/chi phí Ex01–Ex02.

Nguồn là bản công bố SciMKG trên [Zenodo, record 19691725](https://zenodo.org/records/19691725),
revision 4, cập nhật `2026-04-22T08:44:07.233868+00:00`, giấy phép CC BY 4.0.
Nhóm đặt tên thư mục bộ dữ liệu là `MOOC`. Đầu vào lấy từ `RawData.zip`;
nhãn tác giả lấy từ `Groundtruth.zip`. Danh sách được cố định trước khi chạy mô hình.

## Bài đã chọn và phạm vi thực nghiệm

| Mã bài | Môn | Tên bài | Đoạn | Nhãn | Mốc văn bản |
|---|---|---|---:|---:|---|
| `nervous-system` | Sinh học | Cấu tạo hệ thần kinh | 14 | 30 | 00:02–16:56 |
| `amphibian-reproduction` | Sinh học | Sinh sản và phát triển ở động vật lưỡng cư | 7 | 57 | 00:06–08:20 |
| `atmospheric-pressure` | Vật lý | Áp suất khí quyển — tiết 1 | 12 | 21 | 00:07–14:47 |
| `buoyancy` | Vật lý | Lực đẩy — tiết 1 | 14 | 19 | 00:09–17:31 |
| `sulfuric-acid-and-sulfate` | Hóa học | Axit sulfuric và ion sulfate | 15 | 13 | 00:01–11:06 |
| `proteins` | Hóa học | Protein | 13 | 48 | 00:05–16:58 |

- **Ex01:** dùng `nervous-system`.
- **Ex02:** dùng cả sáu bài, cùng ba cấu hình trên từng bài: đầy đủ, tắt
  verification và tắt augmentation; tổng cộng 18 lượt chạy dự kiến.
- Gộp và loại trùng dự đoán sau Integration, trước Augmentation, theo từng
  bài; chấm với nhãn của đúng bài đó. Báo cáo P/R/F1 từng bài và trung bình
  cộng của từng chỉ số trên sáu bài, cùng chi phí/thời gian từng cấu hình.
- Với Augmentation, ghi chi phí và số khái niệm bổ sung. Chưa có nhãn chuẩn
  tương ứng để chấm chất lượng bổ sung hoặc căn chỉnh đa phương thức.

Tổng 188 là tổng số nhãn của sáu bài; không phải số khái niệm riêng biệt
trên toàn bộ sáu bài. Đây là mẫu nhỏ được ưu tiên theo độ ngắn và tính hợp
lệ của văn bản, chưa phải mẫu đại diện cho toàn tập.

## Đối chiếu văn bản và nhãn

Tên thư mục bài trong hai ZIP khớp nhau; toàn bộ tệp văn bản tương ứng được
giữ lại. Tên gốc và đường dẫn thành phần ZIP của từng bài nằm trong
[manifest.json](../data/MOOC/manifest.json). Bộ tải giữ nguyên cả cách viết
`Chemcial`/`chemical` trong đường dẫn công bố.

Hai bài Vật lý trong kế hoạch ban đầu đã được thay trước khi chạy mô hình:

| Bài loại khỏi lựa chọn | Kích thước văn bản | CRC công bố | Lý do |
|---|---:|---|---|
| `8声音的特性_视频课程` — Đặc tính của âm thanh | 4.217 byte | `e641364c` | Dòng 11 kết thúc giữa nội dung, thiếu dấu đóng chuỗi |
| `26眼睛和眼镜_视频课程` — Mắt và kính mắt | 4.307 byte | `f70bc640` | Dòng 7 kết thúc giữa nội dung, thiếu dấu đóng chuỗi |

Các tệp này khớp CRC của ZIP, nên lỗi cắt dở đã có trong nguồn công bố.
Chọn thay bằng hai văn bản Vật lý ngắn nhất qua kiểm tra định dạng, thứ tự
mốc thời gian và có nhãn tương ứng: áp suất khí quyển và lực đẩy. Không
sửa hoặc tự viết tiếp phần văn bản bị thiếu.

## Cách lưu và cố định nhãn

Mỗi bài có ba tệp dưới `data/MOOC/<lesson_id>/`:

- `inputs/lesson.txt`: toàn bộ tệp văn bản công bố, giữ nguyên byte và mốc thời gian.
- `evaluation/groundtruth.txt`: tệp nhãn công bố, giữ nguyên byte.
- `evaluation/gold.json`: nhãn theo bài với `status: frozen`, chỉ bỏ dòng
  trắng và khoảng trắng đầu/cuối từng dòng; không đổi thuật ngữ, thêm nhãn
  hoặc dịch nhãn. Nguồn và hash tệp nhãn gốc đi kèm trong JSON.

`frozen` nghĩa là giữ cố định nhãn công bố cho mọi cấu hình. Nhãn không có
mốc phân đoạn, nên chấm theo toàn bài. Truyền riêng thư mục `inputs` của
từng bài cho EVIA, và chỉ đọc nhãn khi chấm sau suy luận.

**Manifest** là tệp danh mục mô tả bộ dữ liệu. Các đường dẫn trong đó tương
đối với thư mục `data/MOOC/`. Mỗi bài ghi mã, môn, tên gốc, số đoạn, số nhãn,
mốc đầu/cuối, đường dẫn văn bản và nhãn, đường dẫn trong ZIP, kích thước,
CRC và SHA-256. CRC kiểm tra dữ liệu ZIP; SHA-256 giúp xác nhận đúng bản
tệp. Tệp còn ghi nguồn Zenodo, revision, giấy phép, ngày chuẩn bị và các
khoảng byte thực sự đọc trong lượt chuẩn bị thành công.

Lượt thành công đọc 12.348.867 byte từ `RawData.zip` và 67.937 byte từ
`Groundtruth.zip`, gồm chỉ mục và các thành phần được chọn. Cả 12 tệp gốc
đã kiểm tra CRC; hash SHA-256 của tệp gốc và JSON nhãn đã cố định trong
manifest. MD5 toàn ZIP chỉ lấy từ metadata Zenodo, chưa xác minh toàn ZIP.

Lệnh chuẩn bị lại khi đã có manifest kiểm tra cục bộ, dừng nếu tệp bị thay
đổi hoặc thư mục đầu vào có thêm tệp `.txt`, và giữ nguyên ngày chuẩn bị
cùng hash của cả 19 tệp. Lệnh kiểm tra: `python3 scripts/prepare_mooc.py --check`.
Hướng dẫn tải lại nằm trong [README.md](../README.md#chuẩn-bị-dữ-liệu-mooc-cho-ex01-và-ex02).

## Giới hạn còn lại

Đã kiểm tra đầy đủ các tệp văn bản công bố đã chọn. Mức độ đầy đủ so với
video gốc chưa được đối chiếu; các mốc trong bảng là mốc văn bản, chưa phải
thời lượng video đã đo. Ảnh, video, âm thanh và PDF chưa được chuẩn bị ở
bước này. Trước Ex01 cần ghi nhận hoặc bổ sung các tài nguyên này theo
checklist. Không sử dụng `_Intergrationner` hoặc đồ thị sinh sẵn làm nhãn.
