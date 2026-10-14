"""Stage tables and summary for one run, computed from the local journal only (no prices, no inference)."""
from __future__ import annotations

import csv
from pathlib import Path

from .core import STAGES, Journal, read_json, revision, utcnow, write_json

LABELS = {"preprocessing": "Tiền xử lý", "E": "Trích xuất (E)", "V": "Kiểm chứng (V)", "I": "Tích hợp (I)",
          "A": "Bổ sung (A) và truy hồi nguồn", "explanation": "Tạo giải thích (phần của bước A)",
          "image_alignment": "Căn chỉnh ảnh", "video_alignment": "Ghép/cắt video",
          "audio": "Tạo âm thanh (cục bộ)", "export": "Xuất đồ thị"}
# A file that proves a stage finished. E has no file of its own: its span is the proof.
STAGE_OUTPUTS = {"V": "evi.json", "I": "evi.json", "A": "augmentation.json", "image_alignment": "images.json",
                 "explanation": "explanations.json", "audio": "audio.json", "export": "graph.ttl"}
SUM_FIELDS = ("llm_attempts", "llm_completed", "llm_failed", "llm_retries", "cache_hits", "usage_missing",
              "input_tokens_cli", "cached_input_tokens_cli", "cache_write_input_tokens_cli", "output_tokens_cli",
              "inference_seconds", "stage_wall_seconds", "tts_characters", "audio_seconds")
MARKDOWN_COLUMNS = ("step", "status", "llm_completed", "llm_retries", "cache_hits", "input_tokens_cli",
                    "output_tokens_cli", "cached_input_tokens_cli", "stage_wall_seconds")
MARKDOWN_LABELS = ("Bước", "Trạng thái", "Lời gọi thành công", "Thử lại", "Cache cục bộ", "Token vào (CLI)",
                   "Token ra (CLI)", "Token cache (CLI)", "Thời gian (s)")


def cost_rows(events):
    """One row per stage: attempts, completed calls, retries, cache hits and the CLI's own token counts."""
    calls = [e for e in events if e["kind"] == "llm"]
    seen_keys, retry_ids = set(), set()
    for event in sorted(calls, key=lambda e: e.get("started_at_utc", e["created_at_utc"])):
        key = event.get("key")
        if event.get("retry", False) or (key is not None and key in seen_keys):
            retry_ids.add(event["event_id"])
        if key is not None:
            seen_keys.add(key)
    rows = []
    for stage in STAGES:
        relevant = [e for e in events if e.get("stage") == stage]
        llm = [e for e in relevant if e["kind"] == "llm"]
        done = [e for e in llm if e["status"] == "completed"]
        usage = [e.get("usage") or {} for e in done]
        spans = [e for e in relevant if e["kind"] == "span"]
        span_ids = {s["event_id"] for s in spans}
        failed = any(e.get("status") in ("failed", "interrupted") for e in relevant)
        rows.append({"stage": stage, "step": LABELS[stage],
            "status": "not_run" if not relevant else "partial" if failed else "measured",
            "llm_attempts": len(llm), "llm_completed": len(done),
            "llm_failed": sum(e["status"] in ("failed", "interrupted") for e in llm),
            "llm_retries": sum(e["event_id"] in retry_ids for e in llm),
            "cache_hits": sum(e["kind"] == "cache" and e["status"] == "completed" for e in relevant),
            "usage_missing": sum(u.get("input_tokens") is None for u in usage),
            "input_tokens_cli": sum(u.get("input_tokens") or 0 for u in usage),
            "cached_input_tokens_cli": sum(u.get("cached_input_tokens") or 0 for u in usage),
            "cache_write_input_tokens_cli": sum(u.get("cache_write_tokens") or 0 for u in usage),
            "output_tokens_cli": sum(u.get("output_tokens") or 0 for u in usage),
            "inference_seconds": round(sum(e.get("elapsed_seconds", 0) for e in llm), 6),
            "stage_wall_seconds": round(sum(e.get("elapsed_seconds", 0) for e in spans
                                            if e.get("parent_event_id") not in span_ids), 6),
            "tts_characters": sum(e.get("character_count", 0) for e in relevant if e["kind"] == "local"),
            "audio_seconds": round(sum((e.get("output") or {}).get("duration_seconds", 0) for e in relevant
                                       if e["kind"] == "local" and e["status"] == "completed"), 3)})
    return rows


def totals(rows):
    return {name: round(sum(r[name] for r in rows), 6) for name in SUM_FIELDS}


def stage_status(root, events):
    finished = {e["stage"] for e in events if e["kind"] == "span" and e.get("status") == "completed"}
    status = {"E": "done" if "E" in finished else "not_done"}
    for stage in ("V", "I", "A", "image_alignment", "explanation", "audio", "export"):
        status[stage] = "done" if (Path(root) / STAGE_OUTPUTS[stage]).exists() else "not_done"
    return status


def markdown(rows):
    lines = ["| " + " | ".join(MARKDOWN_LABELS) + " |", "| " + " | ".join("---" for _ in MARKDOWN_COLUMNS) + " |"]
    for row in rows:
        values = []
        for column in MARKDOWN_COLUMNS:
            value = row[column]
            values.append(f"{value:.1f}" if isinstance(value, float) else str(value))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines) + "\n"


def report_run(root):
    """Write cost.csv, cost.md, cost.json, summary.json and report.md for one run; return the summary."""
    root = Path(root)
    lesson, config = read_json(root / "lesson.json"), read_json(root / "config.json")
    events = Journal(root).events()
    rows = cost_rows(events)
    cost = totals(rows)
    prior = read_json(root / "summary.json") if (root / "summary.json").exists() else {}
    result = {**prior, "lesson_id": lesson["id"], "model": config["model"], "reported_at_utc": utcnow(),
              "cost": cost, "stage_status": stage_status(root, events),
              "input_inventory": {"text_segments": len(lesson["segments"]), "images": len(lesson["images"]),
                                  "verified_video_duration_seconds": lesson.get("video_duration_seconds")},
              "missing_resources": lesson["missing_resources"], "report_source_revision": revision(),
              "quality_review": "not_measured_in_ex01"}
    with (root / "cost.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (root / "cost.md").write_text(markdown(rows), encoding="utf-8")
    write_json(root / "cost.json", {"stages": rows, "totals": cost})
    write_json(root / "summary.json", result)
    lines = [f"# Ex01: {lesson['id']} ({config['model']})", "",
             "Số đo từ nhật ký: lời gọi, token do CLI báo, thời gian. Tiền theo giá API được tính ở bước phân tích.", "",
             markdown(rows),
             f"Tổng: {cost['llm_completed']} lời gọi thành công, {cost['input_tokens_cli']} token vào và "
             f"{cost['output_tokens_cli']} token ra (CLI báo).", "",
             "Tài nguyên thiếu: " + (", ".join(lesson["missing_resources"]) or "không") + ".", "",
             "Trạng thái bước: " + ", ".join(f"{k}={v}" for k, v in result["stage_status"].items()) + ".", ""]
    (root / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return result
