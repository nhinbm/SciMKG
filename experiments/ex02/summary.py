"""Ex02 tables across configurations and lessons, from saved run folders only (no model or network calls).

Cost uses Ex01's API-like rule: input tokens counted with o200k_base on the prompt and schema, output tokens from
the CLI, no cache, priced with scripts/experiments/ex-01/prices.json. Only stages E, V and A are counted.
"""
from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
from statistics import mean

from experiments.ex01.core import ROOT, read_json, write_json
from .lessons import lesson_ids
from .pipeline import CONFIGURATIONS
from .scoring import score_evi

ANALYSIS_ROOT = ROOT / "runs/analysis/ex02"
# Ex01 ran the full configuration on this lesson with the same model and protocol; Ex02 reuses its E/V/I and A.
REUSED = {("full", "nervous-system"): ROOT / "runs/pipeline/{model}/nervous-system"}
COST_STAGES = ("E", "V", "A")


def ex01_analysis():
    spec = importlib.util.spec_from_file_location("scimkg_ex01_analysis", ROOT / "scripts/experiments/ex-01/analyze.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def folder_for(model, configuration, lesson_id):
    from .cli import run_folder
    folder = run_folder(model, configuration, lesson_id)
    reused = REUSED.get((configuration, lesson_id))
    if not (folder / "evi.json").exists() and reused is not None:
        return Path(str(reused).format(model=model)), "ex01_run"
    return folder, "ex02_run"


def run_cost(folder, price, encoder, analysis):
    row = {f"{stage}_calls": 0 for stage in COST_STAGES}
    row.update(api_input=0, api_output=0, cli_input=0, cli_output=0, inference_seconds=0.0)
    for event in analysis.read_events(folder):
        if event["kind"] != "llm" or event["status"] != "completed" or event["stage"] not in COST_STAGES:
            continue
        usage, inputs = event.get("usage") or {}, event["inputs"]
        row[f"{event['stage']}_calls"] += 1
        row["api_input"] += len(encoder.encode(inputs["prompt"])) + len(encoder.encode(json.dumps(inputs["schema"], ensure_ascii=False)))
        row["api_output"] += usage.get("output_tokens") or 0
        row["cli_input"] += usage.get("input_tokens") or 0
        row["cli_output"] += usage.get("output_tokens") or 0
        row["inference_seconds"] += event["elapsed_seconds"]
    row["api_cost_usd"] = round(analysis.usd(row["api_input"], price["input"]) + analysis.usd(row["api_output"], price["output"]), 6)
    row["inference_seconds"] = round(row["inference_seconds"], 1)
    return row


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(dict.fromkeys(k for r in rows for k in r)))
        writer.writeheader()
        writer.writerows(rows)


def summarize(model="gpt-6-luna"):
    import tiktoken
    analysis = ex01_analysis()
    encoder = tiktoken.get_encoding(analysis.TOKENIZER)
    price = read_json(ROOT / "scripts/experiments/ex-01/prices.json")["models"][model]
    rows = []
    for configuration in CONFIGURATIONS:
        for lesson_id in lesson_ids():
            folder, source = folder_for(model, configuration, lesson_id)
            if not (folder / "evi.json").exists():
                rows.append({"configuration": configuration, "lesson_id": lesson_id, "status": "missing"})
                continue
            evi = read_json(folder / "evi.json")
            if evi["rounds"] != CONFIGURATIONS[configuration] or evi["model"] != model:
                raise ValueError(f"{folder} does not match {configuration} with {model}")
            quality = score_evi(evi, lesson_id)
            final, pool = quality["final"], quality["extraction_pool"]
            augmentation = read_json(folder / "augmentation.json") if (folder / "augmentation.json").exists() else None
            rows.append({"configuration": configuration, "lesson_id": lesson_id,
                         "status": "complete" if augmentation else "evi_only", "source": source, "folder": str(folder.relative_to(ROOT)),
                         "gold": final["gold"], "predicted": final["predicted"], "matched": final["matched"],
                         "precision": round(final["precision"], 4), "recall": round(final["recall"], 4), "f1": round(final["f1"], 4),
                         "substring_f1": round(final["substring_f1"], 4),
                         "pool_predicted": pool["predicted"], "pool_recall": round(pool["recall"], 4), "pool_f1": round(pool["f1"], 4),
                         "added_concepts": len(augmentation["additions"]) if augmentation else None,
                         **run_cost(folder, price, encoder, analysis)})
    scored = [r for r in rows if r["status"] != "missing"]
    full = {r["lesson_id"]: r for r in scored if r["configuration"] == "full"}
    by_config = []
    for configuration in CONFIGURATIONS:
        mine = [r for r in scored if r["configuration"] == configuration]
        if not mine:
            continue
        paired = [r for r in mine if r["lesson_id"] in full]
        by_config.append({"configuration": configuration, "rounds": CONFIGURATIONS[configuration], "lessons": len(mine),
            **{f"macro_{m}": round(mean(r[m] for r in mine), 4) for m in ("precision", "recall", "f1", "substring_f1", "pool_recall")},
            "calls": sum(r["E_calls"] + r["V_calls"] + r["A_calls"] for r in mine),
            "api_input": sum(r["api_input"] for r in mine), "api_output": sum(r["api_output"] for r in mine),
            "api_cost_usd": round(sum(r["api_cost_usd"] for r in mine), 6),
            # "k of n": lessons where this configuration's F1 is below the full configuration on the same lesson.
            "f1_below_full": None if configuration == "full" else f"{sum(r['f1'] < full[r['lesson_id']]['f1'] for r in paired)} / {len(paired)}"})
    out = ANALYSIS_ROOT / model
    write_csv(out / "per_run.csv", rows)
    write_csv(out / "by_configuration.csv", by_config)
    result = {"model": model, "runs_scored": len(scored), "runs_expected": len(CONFIGURATIONS) * len(lesson_ids()),
              "by_configuration": by_config, "output": str(out.relative_to(ROOT))}
    write_json(out / "summary.json", result)
    return result
