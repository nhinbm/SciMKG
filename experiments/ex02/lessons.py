"""Text-only lesson inputs for Ex02, built offline from the pinned MOOC release in data/MOOC."""
from __future__ import annotations

from pathlib import Path

from experiments.ex01.core import ROOT, digest, read_json, seconds, write_json
from experiments.ex01.data import mooc_module

DATASET = ROOT / "data/MOOC"
PREPARATION_ROOT = ROOT / "runs/preprocessing/mooc"


def lesson_ids(dataset=DATASET):
    return [entry["lesson_id"] for entry in read_json(Path(dataset) / "manifest.json")["lessons"]]


def prepare_lesson(lesson_id, *, dataset=DATASET, root=PREPARATION_ROOT):
    """Write runs/preprocessing/mooc/<lesson>/lesson.json and return its path.

    Ex02 stops after A, so images are not part of the input; Ex01's lesson.json in the parent folder is untouched.
    """
    module = mooc_module()
    dataset = Path(dataset)
    manifest = module.verify_dataset(dataset)
    entry = next((e for e in manifest["lessons"] if e["lesson_id"] == lesson_id), None)
    if entry is None:
        raise ValueError(f"Unknown lesson: {lesson_id}")
    text = (dataset / lesson_id / "inputs" / "lesson.txt").read_bytes()
    if digest(text) != entry["input"]["sha256"]:
        raise ValueError("Lesson text differs from the manifest")
    segments = [{"id": f"segment-{i+1:03d}", **s} for i, s in enumerate(module.parse_transcript(text))]
    if len(segments) != entry["segment_count"]:
        raise ValueError("Segment count differs from the manifest")
    lesson = {"id": lesson_id, "subject": entry["subject"], "language": entry["language"],
              "title_vi": entry["title_vi"], "title_original": entry["title_original"],
              "source_url": manifest["record_url"], "segments": segments, "images": [], "video": None,
              "input_sha256": entry["input"]["sha256"],
              "missing_resources": ["images_not_used_in_ex02", "verified_original_video", "original_pdf"],
              "transcript_span_seconds": seconds(segments[-1]["end"]) - seconds(segments[0]["start"]),
              "video_duration_seconds": None, "historical_preprocessing": "not_measured",
              "quality_review": "ex02_concept_labels"}
    path = Path(root) / lesson_id / "lesson.json"
    if path.exists() and read_json(path) != lesson:
        raise ValueError(f"Prepared lesson changed: {path}")
    write_json(path, lesson)
    return path
