"""Chuẩn bị sáu bài MOOC có nhãn tác giả, chỉ tải thành phần ZIP được chọn."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import urllib.request
import zipfile
import zlib


RECORD_URL = "https://zenodo.org/records/19691725"
METADATA_URL = "https://zenodo.org/api/records/19691725"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[2] / "data" / "MOOC"
ARCHIVES = {
    "RawData.zip": (5478401384, "md5:afe8af58643089eb998c7fd15ff1ef98"),
    "Groundtruth.zip": (131337, "md5:cc7e142c1685636bfbbe47b3dfa6606f"),
}
# Danh sách cố định trước khi chạy mô hình. Kích thước và CRC từ chỉ mục tác giả.
LESSONS = (
    ("nervous-system", "Biology", "Cấu tạo hệ thần kinh",
     "Biology/chuyi/2", "biology", "27神经系统的组成_视频课程",
     (3671, "4845aadb"), (408, "5ddd392a")),
    ("amphibian-reproduction", "Biology", "Sinh sản và phát triển ở động vật lưỡng cư",
     "Biology/chuer/2", "biology", "10两栖动物的生殖和发育_视频课程",
     (5106, "f7cab188"), (606, "a4fef9ff")),
    ("atmospheric-pressure", "Physics", "Áp suất khí quyển — tiết 1",
     "Physics/chuer2", "physics", "17大气压强（第一课时）_视频课程",
     (6810, "8b15858e"), (300, "54e3e8e4")),
    ("buoyancy", "Physics", "Lực đẩy — tiết 1",
     "Physics/chuer2", "physics", "21浮力（第一课时）_视频课程",
     (8735, "1bb246c5"), (254, "bae4e747")),
    ("sulfuric-acid-and-sulfate", "Chemistry", "Axit sulfuric và ion sulfate",
     "Chemcial/bx2", "chemical", "4（合格考水平）硫酸及硫酸根",
     (5278, "a03dc927"), (173, "de992eb2")),
    ("proteins", "Chemistry", "Protein",
     "Chemcial/bx2", "chemical", "40蛋白质",
     (5955, "01379ecf"), (564, "9a543baa")),
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def specifications():
    for lesson_id, subject, title, course, discipline, name, text_pin, gold_pin in LESSONS:
        yield {
            "lesson_id": lesson_id, "subject": subject, "title_vi": title,
            "title_original": name, "language": "zh",
            "members": {
                "input": f"Natural Science Disciplines/{course}/{name}/{name}.txt",
                "groundtruth": f"{discipline}/{name}/groundtruth.txt",
            },
            "pins": {"input": text_pin, "groundtruth": gold_pin},
        }


class RangeReader(io.RawIOBase):
    """Tệp ZIP truy cập ngẫu nhiên qua HTTP 206, với giới hạn tải và bộ đệm RAM."""

    def __init__(self, url, *, expected_size=None, max_bytes=24_000_000, opener=None):
        self.url = url
        self.opener = opener or urllib.request.urlopen
        self.size = expected_size
        self.max_bytes = max_bytes
        self.position = self.transferred = 0
        self.requests = []
        self.buffers = []
        self.fetch("bytes=-65558", 65558)

    def fetch(self, interval, limit):
        request = urllib.request.Request(
            self.url, headers={"Range": interval, "User-Agent": "SciMKG-MOOC-preparation/1.0"}
        )
        with self.opener(request, timeout=30) as response:
            if response.status != 206:
                raise ValueError("Máy chủ không hỗ trợ HTTP Range; dừng tải ZIP")
            match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)",
                                 response.headers.get("Content-Range", ""))
            if not match:
                raise ValueError("Content-Range không hợp lệ")
            start, end, total = map(int, match.groups())
            count = end - start + 1
            if not 0 <= start <= end < total:
                raise ValueError("Khoảng byte không hợp lệ")
            if self.size is not None and total != self.size:
                raise ValueError("Kích thước ZIP thay đổi so với bản đã cố định")
            if count > limit or self.transferred + count > self.max_bytes:
                raise ValueError("Vượt giới hạn tải mẫu")
            if interval.startswith("bytes=-"):
                if end != total - 1 or count != min(limit, total):
                    raise ValueError("Range phần cuối không khớp")
            elif interval != f"bytes={start}-{end}":
                raise ValueError("Máy chủ trả sai khoảng byte")
            data = response.read(count + 1)
            if len(data) != count:
                raise ValueError("Phản hồi Range bị cắt hoặc dài hơn yêu cầu")
        self.size = total
        self.transferred += count
        self.buffers.append((start, data))
        self.requests.append({"range": interval, "bytes": count, "sha256": sha256(data)})
        return data

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        if whence not in (0, 1, 2):
            raise ValueError("Kiểu seek không hợp lệ")
        position = offset if whence == 0 else self.position + offset if whence == 1 else self.size + offset
        if position < 0:
            raise ValueError("Vị trí ZIP âm")
        self.position = position
        return position

    def read(self, size=-1):
        stop = self.size if size < 0 else min(self.size, self.position + size)
        if stop <= self.position:
            return b""
        for start, block in self.buffers:
            if start <= self.position and stop <= start + len(block):
                data = block[self.position - start:stop - start]
                break
        else:
            data = self.fetch(f"bytes={self.position}-{stop - 1}", stop - self.position)
        self.position = stop
        return data


def parse_transcript(data: bytes):
    segments = []
    pattern = r'^"(\d{2}:\d{2}(?::\d{2})?)-(\d{2}:\d{2}(?::\d{2})?)"\s*:\s*"(.+)"[,]?$'
    previous_end = -1
    for line_number, line in enumerate(data.decode("utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        match = re.fullmatch(pattern, line.strip())
        if not match:
            raise ValueError(f"Đoạn văn bản không hợp lệ tại dòng {line_number}")
        start, end, text = match.groups()
        times = []
        for stamp in (start, end):
            parts = [int(part) for part in stamp.split(":")]
            if any(part >= 60 for part in parts[1:]):
                raise ValueError(f"Mốc thời gian không hợp lệ tại dòng {line_number}")
            times.append(sum(part * 60 ** index for index, part in enumerate(reversed(parts))))
        if times[0] < previous_end or times[1] <= times[0] or not text.strip():
            raise ValueError(f"Đoạn chồng lấn, sai thứ tự hoặc rỗng tại dòng {line_number}")
        previous_end = times[1]
        segments.append({"start": start, "end": end, "text": text})
    if not segments:
        raise ValueError("Văn bản bài học rỗng")
    return segments


def published_concepts(data: bytes):
    concepts = [line.strip() for line in data.decode("utf-8-sig").splitlines() if line.strip()]
    if not concepts:
        raise ValueError("Nhãn công bố rỗng")
    return concepts


def file_info(data, *, path, archive, member):
    return {
        "path": path, "archive": archive, "archive_member": member,
        "source_url": f"{RECORD_URL}/files/{archive}", "bytes": len(data),
        "crc32": f"{zlib.crc32(data):08x}", "sha256": sha256(data),
    }


def validate_pin(data, pin, member):
    if (len(data), f"{zlib.crc32(data):08x}") != tuple(pin):
        raise ValueError(f"Thành phần khác bản đã chọn: {member}")


def lesson_bundle(spec, text, labels):
    for role, data in (("input", text), ("groundtruth", labels)):
        validate_pin(data, spec["pins"][role], spec["members"][role])
    try:
        segments = parse_transcript(text)
    except ValueError as error:
        raise ValueError(f"Bài {spec['lesson_id']}: {error}") from error
    concepts = published_concepts(labels)
    lesson_id = spec["lesson_id"]
    input_path = f"{lesson_id}/inputs/lesson.txt"
    label_path = f"{lesson_id}/evaluation/groundtruth.txt"
    gold_path = f"{lesson_id}/evaluation/gold.json"
    gold = {
        "lesson_id": lesson_id, "status": "frozen", "scope": "lesson",
        "concepts": concepts,
        "provenance": {
            "source": "author_published", "record_url": RECORD_URL,
            "archive": "Groundtruth.zip", "archive_member": spec["members"]["groundtruth"],
            "original_sha256": sha256(labels),
            "normalization": "Chỉ bỏ dòng trắng và khoảng trắng đầu/cuối từng dòng.",
        },
    }
    gold_data = json_bytes(gold)
    entry = {key: spec[key] for key in ("lesson_id", "subject", "title_vi", "title_original", "language")}
    entry.update({
        "segment_count": len(segments), "label_count": len(concepts),
        "unique_label_count": len(set(concepts)),
        "first_timestamp": segments[0]["start"], "last_timestamp": segments[-1]["end"],
        "label_scope": "lesson", "label_status": "frozen",
        "input": file_info(text, path=input_path, archive="RawData.zip", member=spec["members"]["input"]),
        "groundtruth": file_info(labels, path=label_path, archive="Groundtruth.zip", member=spec["members"]["groundtruth"]),
        "gold": {"path": gold_path, "bytes": len(gold_data), "sha256": sha256(gold_data)},
    })
    return entry, {input_path: text, label_path: labels, gold_path: gold_data}


def read_metadata(opener=None):
    opener = opener or urllib.request.urlopen
    with opener(urllib.request.Request(METADATA_URL), timeout=30) as response:
        raw = response.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError("Metadata quá lớn")
    metadata = json.loads(raw)
    if metadata["id"] != 19691725:
        raise ValueError("Sai bản công bố Zenodo")
    files = {entry["key"]: entry for entry in metadata["files"]}
    for name, pin in ARCHIVES.items():
        if (files[name]["size"], files[name]["checksum"]) != pin:
            raise ValueError(f"Metadata {name} khác bản đã cố định")
    return metadata


def download_archive(name, selected, opener=None):
    url = f"{RECORD_URL}/files/{name}"
    reader = RangeReader(url, expected_size=ARCHIVES[name][0], opener=opener)
    payloads = {}
    with zipfile.ZipFile(reader, metadata_encoding="gbk") as archive:
        entries = sorted(archive.infolist(), key=lambda item: item.header_offset)
        ends = {entry.header_offset: following.header_offset for entry, following in zip(entries, entries[1:])}
        # start_dir do zipfile tính từ chỉ mục, kể cả ZIP64.
        if entries:
            ends[entries[-1].header_offset] = archive.start_dir
        for member, pin in selected:
            info = archive.getinfo(member)
            if (info.file_size, f"{info.CRC:08x}") != tuple(pin):
                raise ValueError(f"Chỉ mục khác bản đã chọn: {member}")
            start, stop = info.header_offset, ends[info.header_offset]
            if not 0 < stop - start <= 2_000_000:
                raise ValueError(f"Thành phần vượt giới hạn mẫu: {member}")
            # Đọc trọn thành phần một lần; zipfile đọc từ bộ đệm và tự kiểm tra CRC.
            if not any(begin <= start and stop <= begin + len(block) for begin, block in reader.buffers):
                reader.fetch(f"bytes={start}-{stop - 1}", stop - start)
            data = archive.read(info)
            validate_pin(data, pin, member)
            payloads[member] = data
            print(f"Đã đọc {name}: {member}", flush=True)
    receipt = {
        "source_url": url, "archive_bytes": reader.size,
        "published_checksum": ARCHIVES[name][1], "whole_archive_checksum_verified": False,
        "transferred_bytes": reader.transferred, "requests": reader.requests,
    }
    return payloads, receipt


def verify_dataset(output: Path):
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    if manifest["dataset"] != "MOOC" or manifest["record_url"] != RECORD_URL:
        raise ValueError("Manifest khác bộ dữ liệu đã chọn")
    specs = list(specifications())
    if [entry["lesson_id"] for entry in manifest["lessons"]] != [spec["lesson_id"] for spec in specs]:
        raise ValueError("Danh sách bài khác lựa chọn đã cố định")
    for spec, entry in zip(specs, manifest["lessons"]):
        lesson_id = spec["lesson_id"]
        # Không dùng đường dẫn do manifest cung cấp để đọc tệp ngoài phạm vi.
        text_path = output / lesson_id / "inputs" / "lesson.txt"
        label_path = output / lesson_id / "evaluation" / "groundtruth.txt"
        expected, files = lesson_bundle(spec, text_path.read_bytes(), label_path.read_bytes())
        if entry != expected:
            raise ValueError(f"Hash hoặc metadata thay đổi: {lesson_id}")
        for relative_path, data in files.items():
            if (output / relative_path).read_bytes() != data:
                raise ValueError(f"Tệp đã cố định bị thay đổi: {relative_path}")
        if set(text_path.parent.rglob("*.txt")) != {text_path}:
            raise ValueError(f"Thư mục inputs có tệp văn bản ngoài bài đã chọn: {lesson_id}")
    return manifest


def prepare_dataset(output: Path, *, opener=None):
    if (output / "manifest.json").exists():
        return verify_dataset(output)
    metadata = read_metadata(opener)
    specs = list(specifications())
    payloads, receipts = {}, {}
    for archive, role in (("RawData.zip", "input"), ("Groundtruth.zip", "groundtruth")):
        print(f"Đang đọc chỉ mục {archive}…", flush=True)
        selected = [(spec["members"][role], spec["pins"][role]) for spec in specs]
        payloads[role], receipts[archive] = download_archive(archive, selected, opener)
    lessons, files = [], {}
    for spec in specs:
        entry, bundle = lesson_bundle(spec, payloads["input"][spec["members"]["input"]],
                                      payloads["groundtruth"][spec["members"]["groundtruth"]])
        lessons.append(entry)
        files.update(bundle)
    # Xác nhận mọi bài trước khi ghi. Không ghi đè tệp cục bộ khác nội dung nguồn.
    for relative_path, data in files.items():
        target = output / relative_path
        if target.exists() and target.read_bytes() != data:
            raise ValueError(f"Tệp cục bộ khác nguồn, dừng ghi: {relative_path}")
    manifest = {
        "schema_version": 1, "dataset": "MOOC", "record_url": RECORD_URL,
        "record_revision": metadata["revision"], "record_updated": metadata["updated"],
        "source_title": metadata["title"], "license": metadata["metadata"]["license"]["id"],
        "prepared_at_utc": datetime.now(timezone.utc).isoformat(),
        "path_base": "Các đường dẫn tệp tương đối với thư mục chứa manifest.json.",
        "selection": "Hai bài văn bản ngắn hợp lệ có nhãn công bố ở mỗi môn; chọn trước khi chạy mô hình.",
        "integrity": "Đã kiểm tra CRC và SHA-256 từng tệp; MD5 toàn ZIP chỉ ghi từ metadata Zenodo.",
        "resources_prepared": ["lesson_text", "published_concept_labels"],
        "video_duration_verified": False,
        "archives": receipts, "lessons": lessons,
    }
    for relative_path, data in files.items():
        target = output / relative_path
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    output.mkdir(parents=True, exist_ok=True)
    (output / "manifest.json").write_bytes(json_bytes(manifest))
    return verify_dataset(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help="Thư mục bộ dữ liệu; mặc định data/MOOC trong fork SciMKG")
    parser.add_argument("--check", action="store_true", help="Chỉ kiểm tra dữ liệu cục bộ, không truy cập mạng")
    args = parser.parse_args()
    try:
        manifest = verify_dataset(args.output) if args.check else prepare_dataset(args.output)
    except (ValueError, OSError, KeyError, zipfile.BadZipFile) as error:
        parser.exit(1, f"Chuẩn bị/kiểm tra MOOC thất bại: {error}\n")
    print(json.dumps({"valid": True, "lessons": len(manifest["lessons"]),
                      "segments": sum(entry["segment_count"] for entry in manifest["lessons"]),
                      "labels": sum(entry["label_count"] for entry in manifest["lessons"]),
                      "manifest": str(args.output / "manifest.json")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
