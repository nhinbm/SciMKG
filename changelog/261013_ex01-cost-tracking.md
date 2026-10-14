# Ex01: đo toàn bài và theo dõi W&B/Weave

## Thay đổi

- Bộ chạy Ex01 trong fork, dùng trực tiếp E/V/I của `NER.py`, Codex thuê bao và TTS cục bộ.
- Extraction truyền lỗi lên bộ chạy, không âm thầm bỏ đoạn.
- Hai biến thể ConceptNet: giữ luật trống và chọn đầu mút tám quan hệ rồi lọc bằng LLM;
  dùng chung E/V/I, ghi riêng chi phí phát sinh và dựng riêng giả định.
- Tải ảnh đúng bài qua Range với cache, CRC/SHA-256; kiểm tra sáu bài trước khi chọn.
- Nhật ký bền vững cho mọi lần thử, cache, usage, nguồn và thời gian; snapshot giá ngày chạy,
  khoảng ước tính khi CLI không cung cấp cache-write.
- W&B Models lưu hai run, bảng và artifact; Weave liên kết từng sự kiện với run ID, giữ WAL.
  Đồng bộ hoặc tính lại báo cáo không gọi lại mô hình.
- Lệnh tiền xử lý video/PDF/transcript/clip đã kiểm tra trên dữ liệu giả lập.
- Theo phản hồi người dùng, thêm ngân sách mặc định 20 lời gọi mới/đợt, 300 giây trước/giữa lời gọi,
  tệp STOP và giữ cache khi dừng. Thêm bảng so giá Terra/Luna mà không chạy mô hình mới.
- Bộ đọc ConceptNet browser kiểm tra URI cạnh; lỗi dịch vụ kích hoạt đường browser dự phòng,
  không lặp lại API hỏng trên mọi khái niệm. Snapshot mã và lịch sử phục hồi giữ bằng chứng trước/sau sửa.
- Tổng phần usage đã biết vẫn giữ chi phí của lần thành công khi cùng bước có lần thiếu usage.
  Kiểm tra công khai tắt xác thực `.netrc`; script audit đối chiếu usage gốc và replay cache không suy luận.
- Hoàn tất riêng nhánh ConceptNet bằng nguồn cố định, tối đa 5 lời gọi mới; thực dùng 3.
  Sửa tổng W&B khi tiếp tục run bằng cập nhật từng trường có tên dạng dấu chấm và khôi phục cha/con trace.
  Công khai bằng quyền `USER_READ`; xác minh hai run, bảng và trace qua kết nối không xác thực.
- Thêm W&B Report về token (tổng, ba biểu đồ và bảng từng bước), chỉ đọc dữ liệu đã đo.
  Lệnh `report --publish-token-report` cập nhật cùng ID, xác minh bảng công khai và giữ nguyên hash nhật ký.
  Run có các trường `tokens/*` và link báo cáo; trace lịch sử giữ số đo tại `summary.measured_usage`.
- Sửa phần mở đầu Report để giải thích đầu vào, kết quả, token và tiền API giả định;
  thu gọn bảng kỹ thuật, phân biệt giá dựng riêng một cách với tổng thử hai cách.
  Hướng dẫn tệp cần đọc và vai trò cache/log trong `docs/EX01.md`; không di chuyển hay xóa dữ liệu đo.

## Giới hạn

Một mô hình, phép chuẩn hóa Integration và cách hoàn thiện ConceptNet là các điều chỉnh của fork.
Video/PDF gốc và tiền xử lý lịch sử còn thiếu. Không coi usage thuê bao là tiền API thực trả,
không chấm chất lượng chuyên môn trong Ex01. Nguồn Wikipedia thiếu được đánh dấu ở từng giải thích.

## Rà soát sau lượt chạy

- Chuẩn hóa giản thể/phồn thể bằng OpenCC, giữ đồng nghĩa làm bí danh, kiểm tra nhãn ứng viên theo nguồn;
  dữ liệu lịch sử có 17/40 nhãn bổ sung trùng E/V/I sau chuyển chữ. Không ghi đè đầu ra lịch sử.
- Dừng ngay khi hết hạn mức, ghi lần ngắt và phân biệt pause với lỗi; kiểm tra metadata/hash cache.
- Tách cache thành công khỏi bằng chứng truy hồi lỗi; tránh cộng thời gian span lồng nhau và tính giá dài
  trên tổng nhiều lượt; giữ khoản cache-write đã biết khi thiếu số token cache đọc.
- Kiểm tra URI nguồn ConceptNet, đầu vào rỗng/trùng và đối chiếu video khác đoạn; Report lấy cấu hình thực.
- Mã và prompt điều khiển dùng tiếng Anh; protocol 2 cho lượt mới, audit replay nguyên yêu cầu protocol 1.
- Rà 23 tên argument CLI, bỏ một argument hàm xuất đồ thị và bốn import dư; help phân nhóm.
- Sửa chế độ offline để trì hoãn truy cập artifact dùng chung đến khi đồng bộ online.
- Theo yêu cầu người dùng, gỡ bộ test Ex01, dependency `pytest`, cache test và script audit riêng;
  tài liệu và snapshot mã báo cáo không còn tham chiếu script đã gỡ.
- Chuyển dữ liệu sinh ra từ `data/ex01/` vào `runs/ex01/preparation/`, cập nhật mặc định lệnh chạy.
  `runs/` được bỏ qua trong Git; `experiments/ex01/` là mã thực nghiệm cần commit.
- Chuyển mã Ex01 vào `experiments/ex01/`, cập nhật import và đường dẫn snapshot.
  `scripts/run_ex01.py` là entry point 11 dòng; CLI và các thao tác W&B nằm trong module đúng vai trò.
- Rút CLI còn `run` và `report`, bỏ lệnh/argument/import chuẩn bị, kiểm tra và tiền xử lý riêng.
  `run` tự chuẩn bị đầu vào mặc định nếu thiếu; kiểm tra dữ liệu và đăng nhập nằm trong pipeline/tracking.
- Chưa chạy suy luận mới hoặc chỉnh giao diện W&B trong lượt review.

## Kiểm tra

Manifest MOOC hợp lệ (6 bài, 75 đoạn, 188 nhãn). Bộ test Ex01 đã được gỡ theo yêu cầu sau review.
427 mục cache replay không suy luận; 157 WAV và 1.762 trace Weave đã đối chiếu.
Lượt thật và trạng thái công khai được cập nhật tại [EX01](../docs/EX01.md).
