"""Read the pinned MOOC release and download selected lesson images using HTTP Range."""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import subprocess
import time
import urllib.request
import zipfile
import zlib

from .core import ROOT, digest, read_json, seconds, utcnow, write_json


def mooc_module():
    spec = importlib.util.spec_from_file_location("scimkg_mooc_preparation", ROOT / "scripts/preprocessing/prepare_mooc.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CachedResponse(io.BytesIO):
    status = 206
    def __init__(self, data, headers):
        super().__init__(data)
        self.headers = headers


class RangeCache:
    def __init__(self, root, journal):
        self.root, self.journal = Path(root), journal
        self.root.mkdir(parents=True, exist_ok=True)

    def __call__(self, request, timeout=30):
        import urllib.error
        for attempt in range(1, 4):
            try:
                return self.fetch(request, timeout, attempt)
            except (ValueError, urllib.error.HTTPError) as exc:
                if isinstance(exc, ValueError) or exc.code < 500 and exc.code != 429:
                    raise
                if attempt == 3: raise
            except (OSError, TimeoutError):
                if attempt == 3: raise
            time.sleep(2 ** attempt)

    def fetch(self, request, timeout, attempt):
        interval = request.get_header("Range")
        key = digest({"url": request.full_url, "range": interval})
        path = self.root / f"{key}.json"
        blob = self.root / f"{key}.bin"
        if path.exists() and blob.exists():
            saved, data = read_json(path), blob.read_bytes()
            if digest(data) != saved["sha256"]:
                raise ValueError("Cached byte range has changed")
            self.journal.record({"kind": "cache", "stage": "preprocessing", "operation": "archive_range_cache",
                "url": request.full_url, "range": interval, "origin_event_ids": saved["origin_event_ids"],
                "status": "completed", "elapsed_seconds": 0})
            return CachedResponse(data, saved["headers"])
        start, stamp = time.monotonic(), utcnow()
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if response.status != 206:
                    raise ValueError("Server ignored Range; stop to avoid downloading the entire ZIP")
                headers = {"Content-Range": response.headers.get("Content-Range", "")}
                # Read no more than the declared response range and the preparation budget.
                import re
                match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", headers["Content-Range"])
                if not match:
                    raise ValueError("Invalid Content-Range")
                length = int(match[2]) - int(match[1]) + 1
                if not 0 < length <= 16_000_000:
                    raise ValueError("Byte range exceeds the limit")
                data = response.read(length + 1)
                if len(data) != length:
                    raise OSError("Range response is truncated or too long; retry the same byte interval")
            event = self.journal.record({"kind": "http", "stage": "preprocessing", "operation": "archive_range",
                "attempt": attempt, "retry": attempt > 1,
                "url": request.full_url, "range": interval, "bytes": len(data), "http_status": 206,
                "status": "completed", "started_at_utc": stamp, "ended_at_utc": utcnow(),
                "elapsed_seconds": time.monotonic() - start, "api_paid_usd": 0})
            blob.write_bytes(data)
            write_json(path, {"headers": headers, "sha256": digest(data), "origin_event_ids": [event["event_id"]]})
            return CachedResponse(data, headers)
        except Exception as exc:
            self.journal.record({"kind": "http", "stage": "preprocessing", "operation": "archive_range",
                "attempt": attempt, "retry": attempt > 1,
                "url": request.full_url, "range": interval, "status": "failed", "error": str(exc)[:300],
                "started_at_utc": stamp, "ended_at_utc": utcnow(), "elapsed_seconds": time.monotonic() - start})
            raise


def probe(path):
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                             "-of", "json", str(path)], capture_output=True, text=True, timeout=30, check=True)
    duration = float(json.loads(result.stdout)["format"]["duration"])
    if not duration > 0:
        raise ValueError("Video or audio duration must be positive")
    return duration


def verified_video(entry, segments):
    if not entry or entry.get("status") != "verified":
        return None
    path = Path(entry["path"]).resolve()
    # A matching title or an author's graph URL is insufficient evidence.
    matched = set(entry.get("matched_segments", []))
    if not path.is_file() or not entry.get("source_url") or len(matched) < 3:
        raise ValueError("Video verification requires a file, source URL, and three distinct matched segments")
    if entry.get("sha256") != digest(path.read_bytes()):
        raise ValueError("Video differs from the verified file")
    ids = {s["id"] for s in segments}
    if not matched <= ids:
        raise ValueError("Video verification references segments from a different lesson")
    duration = probe(path)
    offset = entry.get("clip_start_seconds", 0)
    if offset < 0 or any(seconds(s["start"]) < offset or seconds(s["end"]) > offset + duration + 0.15 for s in segments):
        raise ValueError("Timestamp lies outside the video")
    return {**entry, "path": str(path), "duration_seconds": duration}


def select_lesson(entries):
    complete = [e for e in entries if e.get("video") and e["image_count"] > 0]
    if complete:
        nervous = next((e for e in complete if e["lesson_id"] == "nervous-system"), None)
        return nervous or min(complete, key=lambda e: (e["segment_count"], e["selection_index"]))
    best_modalities = max(1 + bool(e["image_count"]) + bool(e.get("video")) for e in entries)
    candidates = [e for e in entries if 1 + bool(e["image_count"]) + bool(e.get("video")) == best_modalities]
    return next((e for e in candidates if e["lesson_id"] == "nervous-system"), candidates[0])


def prepare(root, journal, *, dataset=None, lesson_id="auto", video_manifest=None):
    from PIL import Image
    module = mooc_module()
    dataset = Path(dataset or ROOT / "data/MOOC")
    manifest = module.verify_dataset(dataset)
    root = Path(root)
    videos = read_json(video_manifest) if video_manifest else {}
    opener = RangeCache(root / "ranges", journal)
    inventory_path = root / "inventory.json"
    if inventory_path.exists():
        inventory = read_json(inventory_path)
        if inventory["manifest_sha256"] != digest((dataset / "manifest.json").read_bytes()):
            raise ValueError("Manifest changed; the previous inventory cannot be reused")
    else:
        reader = module.RangeReader(manifest["archives"]["RawData.zip"]["source_url"],
                                   expected_size=module.ARCHIVES["RawData.zip"][0], opener=opener)
        with zipfile.ZipFile(reader, metadata_encoding="gbk") as archive:
            files = archive.infolist()
            entries = []
            for index, lesson in enumerate(manifest["lessons"]):
                prefix = lesson["input"]["archive_member"].rsplit("/", 1)[0] + "/"
                images = [{"archive_member": f.filename, "bytes": f.file_size, "crc32": f"{f.CRC:08x}"}
                          for f in files if f.filename.startswith(prefix) and Path(f.filename).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp")]
                entries.append({**lesson, "selection_index": index, "image_count": len(images),
                                "images": sorted(images, key=lambda f: f["archive_member"])})
        inventory = {"created_at_utc": utcnow(), "manifest_sha256": digest((dataset / "manifest.json").read_bytes()),
                     "lessons": entries, "video_pdf_in_archive": False,
                     "historical_preprocessing": "not_measured"}
        write_json(inventory_path, inventory)
    entries = []
    for entry in inventory["lessons"]:
        segments = module.parse_transcript((dataset / entry["input"]["path"]).read_bytes())
        segments = [{"id": f"segment-{i+1:03d}", **s} for i, s in enumerate(segments)]
        entries.append({**entry, "segments": segments, "video": verified_video(videos.get(entry["lesson_id"]), segments)})
    chosen = select_lesson(entries) if lesson_id == "auto" else next(e for e in entries if e["lesson_id"] == lesson_id)
    receipt = {"selection": [{"lesson_id": e["lesson_id"], "segments": e["segment_count"],
                             "images": e["image_count"], "video_verified": bool(e["video"])} for e in entries],
               "lesson_id": chosen["lesson_id"], "reason": "complete_inputs" if chosen["video"] else "best_available_with_missing_video",
               "chosen_at_utc": utcnow()}
    images = []
    reader = None
    for image in chosen["images"]:
        target = dataset / chosen["lesson_id"] / "media" / Path(image["archive_member"]).name
        if not target.exists():
            if reader is None:
                reader = module.RangeReader(manifest["archives"]["RawData.zip"]["source_url"],
                    expected_size=module.ARCHIVES["RawData.zip"][0], max_bytes=64_000_000, opener=opener)
            with zipfile.ZipFile(reader, metadata_encoding="gbk") as archive:
                info = archive.getinfo(image["archive_member"])
                offsets = sorted(f.header_offset for f in archive.infolist())
                import bisect
                position = bisect.bisect_right(offsets, info.header_offset)
                stop = offsets[position] if position < len(offsets) else archive.start_dir
                if not 0 < stop - info.header_offset <= 2_000_000:
                    raise ValueError("Archive image member exceeds the download limit")
                # Fetch one full local member including header and descriptor, avoiding
                # many small network requests while zipfile still verifies CRC.
                reader.fetch(f"bytes={info.header_offset}-{stop-1}", stop - info.header_offset)
                payload = archive.read(image["archive_member"])
            if len(payload) != image["bytes"] or f"{zlib.crc32(payload):08x}" != image["crc32"]:
                raise ValueError("Image does not match the published archive member")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        data = target.read_bytes()
        if f"{zlib.crc32(data):08x}" != image["crc32"]:
            raise ValueError("Local image has changed")
        with Image.open(target) as opened:
            dimensions = opened.size
            opened.verify()
        images.append({**image, "id": target.stem, "path": str(target.resolve()),
                       "sha256": digest(data), "width": dimensions[0], "height": dimensions[1]})
    lesson = {"id": chosen["lesson_id"], "subject": chosen["subject"], "language": chosen["language"],
              "title_vi": chosen["title_vi"], "title_original": chosen["title_original"],
              "source_url": manifest["record_url"], "segments": chosen["segments"], "images": images,
              "video": chosen["video"], "input_sha256": chosen["input"]["sha256"],
              "missing_resources": ([] if chosen["video"] else ["verified_original_video"]) + ["original_pdf", "historical_preprocessing_measurement"],
              "transcript_span_seconds": seconds(chosen["segments"][-1]["end"]) - seconds(chosen["segments"][0]["start"]),
              "video_duration_seconds": chosen["video"]["duration_seconds"] if chosen["video"] else None,
              "historical_preprocessing": "not_measured", "selection": receipt,
              "preparation_journal": str((root / "events.jsonl").resolve()),
              "quality_review": "not_measured_in_ex01"}
    write_json(root / "lesson.json", lesson)
    write_json(root / "selection.json", receipt)
    return lesson


def validate_lesson(lesson):
    from PIL import Image
    if not lesson["segments"]:
        raise ValueError("Lesson has no text segments")
    seen, end = set(), -1
    for segment in lesson["segments"]:
        if segment["id"] in seen or not segment["text"].strip() or seconds(segment["start"]) < end:
            raise ValueError("Duplicate, empty, or overlapping segments")
        end = seconds(segment["end"])
        if end <= seconds(segment["start"]):
            raise ValueError("Segment duration must be positive")
        seen.add(segment["id"])
    image_ids = set()
    for image in lesson["images"]:
        if not image.get("id") or image["id"] in image_ids:
            raise ValueError("Empty or duplicate image ID")
        image_ids.add(image["id"])
        path = Path(image["path"])
        if digest(path.read_bytes()) != image["sha256"]:
            raise ValueError("Image hash has changed")
        with Image.open(path) as opened:
            opened.verify()
    if lesson.get("video"):
        verified_video(lesson["video"], lesson["segments"])
    return {"valid": True, "segments": len(lesson["segments"]), "images": len(lesson["images"]),
            "video_duration_seconds": lesson["video_duration_seconds"], "missing_resources": lesson["missing_resources"]}


def extract_clips(video_path, segments, output):
    """Cut one clip per transcript segment from a verified full video."""
    output, video_path = Path(output), Path(video_path)
    output.mkdir(parents=True, exist_ok=True)
    duration = probe(video_path)
    result = []
    for segment in segments:
        start, stop = seconds(segment["start"]), seconds(segment["end"])
        if stop > duration + 0.15:
            raise ValueError("Segment extends beyond the video")
        target = output / f"{segment['id']}.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(start), "-i", str(video_path),
                        "-t", str(stop-start), "-c:v", "libx264", "-c:a", "aac", str(target)], check=True, timeout=300)
        result.append({"segment_id": segment["id"], "path": str(target.resolve()), "duration_seconds": probe(target), "sha256": digest(target.read_bytes())})
    write_json(output / "clips.json", result)
    return result
