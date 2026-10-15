"""Cost tables (Ex01's journal accounting) and concept quality for one Ex02 run; no inference."""
from __future__ import annotations

import csv
from pathlib import Path

from experiments.ex01.core import Journal, read_json, utcnow, write_json
from experiments.ex01.report import cost_rows, markdown, stage_status, totals
from .scoring import score_evi

STAGES = ("E", "V", "I", "A")


def quality_keys(quality):
    keys = {}
    for level in ("final", "extraction_pool"):
        for metric in ("precision", "recall", "f1", "substring_f1", "predicted", "matched"):
            keys[f"quality/{level}/{metric}"] = quality[level][metric]
    keys["quality/gold_labels"] = quality["final"]["gold"]
    return keys


def report_run(root):
    """Write cost.csv, cost.md, cost.json, quality.json, summary.json and report.md; return the summary."""
    root = Path(root)
    lesson, config = read_json(root / "lesson.json"), read_json(root / "config.json")
    events = Journal(root).events()
    rows = [r for r in cost_rows(events) if r["stage"] in STAGES]
    if config["verification"] == "off":
        for row in rows:
            if row["stage"] in ("V", "I"):
                row["status"] = "off"
    cost = totals(rows)
    prior = read_json(root / "summary.json") if (root / "summary.json").exists() else {}
    status = {k: v for k, v in stage_status(root, events).items() if k in STAGES}
    if config["verification"] == "off":
        status.update(V="off", I="off")
    quality = score_evi(read_json(root / "evi.json"), lesson["id"]) if (root / "evi.json").exists() else None
    if quality:
        write_json(root / "quality.json", quality)
    result = {**prior, "experiment": "Ex02", "lesson_id": lesson["id"], "model": config["model"],
              "configuration": config["configuration"], "rounds": config["rounds"], "reported_at_utc": utcnow(),
              "cost": cost, "stage_status": status,
              "quality": None if quality is None else {k: {m: v for m, v in quality[k].items() if not isinstance(v, list)}
                                                       for k in ("final", "extraction_pool")},
              "quality_keys": quality_keys(quality) if quality else {}}
    with (root / "cost.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (root / "cost.md").write_text(markdown(rows), encoding="utf-8")
    write_json(root / "cost.json", {"stages": rows, "totals": cost})
    write_json(root / "summary.json", result)
    lines = [f"# Ex02: {lesson['id']}, {config['configuration']} ({config['model']}, {config['rounds']} vòng)", "",
             markdown(rows),
             f"Tổng: {cost['llm_completed']} lời gọi thành công, {cost['input_tokens_cli']} token vào và "
             f"{cost['output_tokens_cli']} token ra (CLI báo).", ""]
    if quality:
        for level, label in (("final", "Khái niệm sau E/V/I"), ("extraction_pool", "Ứng viên E (trần recall)")):
            q = quality[level]
            lines.append(f"{label}: {q['predicted']} khái niệm, khớp {q['matched']}/{q['gold']} nhãn; "
                         f"P {q['precision']:.3f}, R {q['recall']:.3f}, F1 {q['f1']:.3f} "
                         f"(khớp chuỗi con, thăm dò: F1 {q['substring_f1']:.3f}).")
        lines.append("")
    lines.append("Trạng thái bước: " + ", ".join(f"{k}={v}" for k, v in status.items()) + ".")
    (root / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result
