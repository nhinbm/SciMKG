"""Kiểm tra thu thập và cố định dữ liệu; các mẫu trong tệp này đều giả lập."""
import io
import json
from pathlib import Path
import re
import zipfile
import zlib

import pytest

from scripts import prepare_mooc as mooc


class Response(io.BytesIO):
    def __init__(self, data, *, status=206, headers=None):
        super().__init__(data)
        self.status = status
        self.headers = headers or {}


def zip_bytes(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def range_opener(raw, calls):
    def opener(request, **kwargs):
        interval = request.headers["Range"]
        calls.append(interval)
        if interval.startswith("bytes=-"):
            start, end = max(0, len(raw) - int(interval[7:])), len(raw) - 1
        else:
            start, end = map(int, re.fullmatch(r"bytes=(\d+)-(\d+)", interval).groups())
        return Response(raw[start:end + 1], headers={"Content-Range": f"bytes {start}-{end}/{len(raw)}"})
    return opener


def pin(data):
    return len(data), f"{zlib.crc32(data):08x}"


def test_download_reads_only_selected_member_and_directory(monkeypatch):
    member, data = "chosen.txt", b"selected fixture"
    raw = zip_bytes({member: data, "unused.bin": b"X" * 100_000})
    monkeypatch.setattr(mooc, "ARCHIVES", {"fixture.zip": (len(raw), "md5:fixture")})
    calls = []
    result, receipt = mooc.download_archive("fixture.zip", [(member, pin(data))], range_opener(raw, calls))
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        unused_start = archive.getinfo("unused.bin").header_offset
    assert result == {member: data}
    assert calls == ["bytes=-65558", f"bytes=0-{unused_start - 1}"]
    assert receipt["transferred_bytes"] < len(raw)
    assert receipt["whole_archive_checksum_verified"] is False


def test_download_handles_zip64_local_header(monkeypatch):
    buffer = io.BytesIO()
    data = b"ZIP64 fixture"
    with zipfile.ZipFile(buffer, "w") as archive:
        with archive.open("chosen.txt", "w", force_zip64=True) as member:
            member.write(data)
        archive.writestr("unused.bin", b"X" * 100_000)
    raw = buffer.getvalue()
    monkeypatch.setattr(mooc, "ARCHIVES", {"fixture.zip": (len(raw), "md5:fixture")})
    result, _ = mooc.download_archive("fixture.zip", [("chosen.txt", pin(data))], range_opener(raw, []))
    assert result == {"chosen.txt": data}


def test_transcript_rejects_truncated_last_line():
    with pytest.raises(ValueError, match="dòng 1"):
        mooc.parse_transcript('"09:30-10:29": "đoạn cuối bị cắt'.encode())


def test_reader_rejects_200_without_reading_body():
    class NoRead(Response):
        def read(self, *args):
            raise AssertionError("Không được đọc toàn ZIP khi máy chủ trả 200")
    with pytest.raises(ValueError, match="HTTP Range"):
        mooc.RangeReader("https://example.org/fixture", opener=lambda *a, **k: NoRead(b"", status=200))


@pytest.mark.parametrize("headers,data,pin_size,budget,message", [
    ({}, b"", None, 100, "Content-Range"),
    ({"Content-Range": "bytes 0-9/100"}, b"x" * 10, None, 100, "phần cuối"),
    ({"Content-Range": "bytes 0-9/10"}, b"x" * 9, None, 100, "bị cắt"),
    ({"Content-Range": "bytes 0-9/10"}, b"x" * 10, 11, 100, "Kích thước"),
    ({"Content-Range": "bytes 0-9/10"}, b"x" * 10, None, 5, "giới hạn"),
])
def test_reader_rejects_invalid_or_unbounded_responses(headers, data, pin_size, budget, message):
    with pytest.raises(ValueError, match=message):
        mooc.RangeReader("https://example.org/fixture", expected_size=pin_size, max_bytes=budget,
                         opener=lambda *a, **k: Response(data, headers=headers))


def test_reader_checks_explicit_range():
    raw = b"X" * 100_000
    valid = range_opener(raw, [])
    def opener(request, **kwargs):
        if request.headers["Range"].startswith("bytes=-"):
            return valid(request, **kwargs)
        return Response(b"x" * 4, headers={"Content-Range": "bytes 1-4/100000"})
    reader = mooc.RangeReader("https://example.org/fixture", opener=opener)
    with pytest.raises(ValueError, match="sai khoảng"):
        reader.read(4)


def test_download_detects_corrupt_member(monkeypatch):
    data = b"unique fixture payload"
    raw = zip_bytes({"chosen.txt": data})
    corrupted = raw.replace(data, b"X" + data[1:], 1)
    monkeypatch.setattr(mooc, "ARCHIVES", {"fixture.zip": (len(raw), "md5:fixture")})
    with pytest.raises(zipfile.BadZipFile, match="CRC"):
        mooc.download_archive("fixture.zip", [("chosen.txt", pin(data))], range_opener(corrupted, []))


@pytest.mark.parametrize("text", [
    "", '"00:00-00:01": ""', '"00:00-00:00": "x"',
    '"00:00-00:60": "x"', '"00:00-00:01": "x"\nđoạn lỗi',
    '"00:00-00:02": "x"\n"00:01-00:03": "y"',
])
def test_transcript_rejects_empty_malformed_or_overlapping_segments(text):
    with pytest.raises(ValueError):
        mooc.parse_transcript(text.encode())


def fixture_dataset(monkeypatch, *, text=None):
    text = text if text is not None else '"00:02-00:10": "课文一"\r\n\r\n"00:10-00:20": "课文二"\r\n'.encode()
    labels = "  作者术语  \r\n\r\n第二术语\r\n作者术语\r\n".encode()
    name = "假数据"
    monkeypatch.setattr(mooc, "LESSONS", (("fixture", "Biology", "Bài giả lập", "Biology/fixture",
                                           "biology", name, pin(text), pin(labels)),))
    spec = next(mooc.specifications())
    archives = {
        "RawData.zip": zip_bytes({spec["members"]["input"]: text}),
        "Groundtruth.zip": zip_bytes({spec["members"]["groundtruth"]: labels}),
    }
    monkeypatch.setattr(mooc, "ARCHIVES", {name: (len(raw), "md5:fixture") for name, raw in archives.items()})
    metadata = {
        "id": 19691725, "revision": 4, "updated": "fixture", "title": "Dữ liệu giả lập",
        "metadata": {"license": {"id": "cc-by-4.0"}},
        "files": [{"key": name, "size": len(raw), "checksum": "md5:fixture"} for name, raw in archives.items()],
    }
    calls = []
    def opener(request, **kwargs):
        if request.full_url == mooc.METADATA_URL:
            calls.append("metadata")
            return Response(mooc.json_bytes(metadata), status=200)
        archive = Path(request.full_url).name
        return range_opener(archives[archive], calls)(request, **kwargs)
    return opener, text, labels, calls


def test_prepare_freezes_original_bytes_and_separates_labels(monkeypatch, tmp_path):
    opener, text, labels, calls = fixture_dataset(monkeypatch)
    manifest = mooc.prepare_dataset(tmp_path, opener=opener)
    assert (tmp_path / "fixture/inputs/lesson.txt").read_bytes() == text
    assert (tmp_path / "fixture/evaluation/groundtruth.txt").read_bytes() == labels
    assert list((tmp_path / "fixture/inputs").iterdir()) == [tmp_path / "fixture/inputs/lesson.txt"]
    gold = json.loads((tmp_path / "fixture/evaluation/gold.json").read_text())
    assert gold["status"] == "frozen" and gold["scope"] == "lesson"
    assert gold["concepts"] == ["作者术语", "第二术语", "作者术语"]
    assert manifest["lessons"][0]["segment_count"] == 2
    assert manifest["lessons"][0]["label_count"] == 3
    assert manifest["lessons"][0]["unique_label_count"] == 2
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    def no_network(*args, **kwargs):
        raise AssertionError("Chạy lại phải kiểm tra cục bộ")
    assert mooc.prepare_dataset(tmp_path, opener=no_network) == manifest
    assert {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("changed", ["input", "original_labels", "gold", "extra_input", "manifest_path"])
def test_check_rejects_changed_files_and_label_leakage(monkeypatch, tmp_path, changed):
    opener, _, _, _ = fixture_dataset(monkeypatch)
    mooc.prepare_dataset(tmp_path, opener=opener)
    if changed == "input":
        (tmp_path / "fixture/inputs/lesson.txt").write_bytes(b"modified")
    elif changed == "original_labels":
        (tmp_path / "fixture/evaluation/groundtruth.txt").write_bytes(b"modified")
    elif changed == "gold":
        (tmp_path / "fixture/evaluation/gold.json").write_text('{"concepts":["invented"]}')
    elif changed == "extra_input":
        (tmp_path / "fixture/inputs/gold.txt").write_text("labels")
    else:
        manifest_path = tmp_path / "manifest.json"
        value = json.loads(manifest_path.read_text())
        value["lessons"][0]["input"]["path"] = "../../unrelated.txt"
        manifest_path.write_bytes(mooc.json_bytes(value))
    with pytest.raises(ValueError):
        mooc.verify_dataset(tmp_path)


def test_malformed_lesson_does_not_write_partial_dataset(monkeypatch, tmp_path):
    opener, _, _, _ = fixture_dataset(monkeypatch, text=b"malformed text")
    output = tmp_path / "MOOC"
    with pytest.raises(ValueError, match="dòng"):
        mooc.prepare_dataset(output, opener=opener)
    assert not output.exists()
