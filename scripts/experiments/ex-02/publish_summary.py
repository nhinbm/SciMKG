#!/usr/bin/env python3
"""Publish Ex02 as one W&B run: the summary tables plus every run's result files as one artifact.

After this run is verified as publicly readable, the per-run Ex02 W&B runs hold nothing it lacks;
wandb_runs.json lists them. The local run folders stay the source of every number.
Makes no model calls. Refuses to publish until all 18 (configuration, lesson) cells are scored.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from experiments.ex01.core import read_json, utcnow, write_json  # noqa: E402
from experiments.ex01.tracking import ENTITY, PROJECT, PUBLIC_ACCESS  # noqa: E402
from experiments.ex02.lessons import lesson_ids  # noqa: E402
from experiments.ex02.pipeline import CONFIGURATIONS  # noqa: E402
from experiments.ex02.scoring import score_evi  # noqa: E402
from experiments.ex02.summary import ANALYSIS_ROOT, folder_for, summarize  # noqa: E402

RESULT_FILES = ("config.json", "lesson.json", "evi.json", "augmentation.json", "cost.json", "summary.json",
                "events.jsonl", "batches.jsonl", "tracking.json")


def collect(model):
    """Every cell's folder, its files for the artifact, its quality and its own W&B run."""
    cells = []
    for configuration in CONFIGURATIONS:
        for lesson_id in lesson_ids():
            folder, source = folder_for(model, configuration, lesson_id)
            receipt = read_json(folder / "tracking.json") if (folder / "tracking.json").exists() else {}
            cells.append({"configuration": configuration, "lesson_id": lesson_id, "source": source, "folder": folder,
                          "files": [folder / name for name in RESULT_FILES if (folder / name).is_file()],
                          "quality": score_evi(read_json(folder / "evi.json"), lesson_id),
                          "wandb_run_id": receipt.get("run_id"), "wandb_run_url": receipt.get("run_url")})
    return cells


def table(path):
    import csv
    import wandb
    with open(path, encoding="utf-8") as stream:
        rows = list(csv.reader(stream))
    return wandb.Table(columns=rows[0], data=rows[1:])


def verify_public(entity, project, run_id, expected):
    """Read the run without credentials and compare one summary value with the local table."""
    import requests
    from wandb import Settings
    query = """query Ex02Summary($name:String!,$entity:String!,$run:String!){
      project(name:$name,entityName:$entity){access run(name:$run){name state summaryMetrics}}}"""
    with requests.Session() as session:
        session.trust_env = False  # otherwise requests authenticates from ~/.netrc
        response = session.post(Settings().base_url.rstrip("/") + "/graphql", timeout=30,
            json={"query": query, "variables": {"name": project, "entity": entity, "run": run_id}})
    response.raise_for_status()
    project_data = (response.json().get("data") or {}).get("project")
    if not project_data or project_data["access"] != PUBLIC_ACCESS or not project_data.get("run"):
        raise RuntimeError("The summary run is not readable without logging in")
    remote = json.loads(project_data["run"]["summaryMetrics"])
    for key, value in expected.items():
        if remote.get(key) != value:
            raise RuntimeError(f"Public summary differs from the local table at {key}")
    return {"verified_at_utc": utcnow(), "anonymous_read": True, "state": project_data["run"]["state"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="gpt-6-luna")
    parser.add_argument("--entity", default=ENTITY)
    parser.add_argument("--project", default=PROJECT)
    parser.add_argument("--dry-run", action="store_true", help="Check the cells and list the artifact without W&B")
    args = parser.parse_args(argv)
    result = summarize(args.model)
    if result["runs_scored"] != result["runs_expected"]:
        raise SystemExit(f"Only {result['runs_scored']} of {result['runs_expected']} cells are scored; finish Ex02 first")
    cells = collect(args.model)
    out = ANALYSIS_ROOT / args.model
    individual = [{k: c[k] for k in ("configuration", "lesson_id", "source", "wandb_run_id", "wandb_run_url")}
                  for c in cells]
    write_json(out / "wandb_runs.json", {"note": "Per-cell W&B runs; the ex01_run row is the Ex01 run and stays.",
                                         "runs": individual})
    summary_keys = {f"{row['configuration']}/macro_{m}": row[f"macro_{m}"]
                    for row in result["by_configuration"] for m in ("precision", "recall", "f1")}
    summary_keys.update({f"{row['configuration']}/api_cost_usd": row["api_cost_usd"] for row in result["by_configuration"]})
    if args.dry_run:
        print(json.dumps({"cells": len(cells), "artifact_files": sum(len(c["files"]) for c in cells) + len(cells),
                          "summary_keys": summary_keys}, ensure_ascii=False, indent=2))
        return 0
    import wandb
    receipt_path = out / "wandb_summary.json"
    receipt = read_json(receipt_path) if receipt_path.exists() else {"run_id": "ex02-" + uuid.uuid4().hex[:8]}
    run = wandb.init(entity=args.entity, project=args.project, id=receipt["run_id"], resume="allow",
                     name=f"ex02-summary-{args.model}", group=f"ex02-{args.model}", job_type="summary",
                     tags=["Ex02", "summary", args.model],
                     config={"experiment": "Ex02", "model": args.model, "configurations": CONFIGURATIONS,
                             "lessons": lesson_ids(), "scoring": cells[0]["quality"]["scoring"],
                             "reused_ex01_run": [c["wandb_run_url"] for c in cells if c["source"] == "ex01_run"]})
    try:
        run.log({"ex02/by_configuration": table(out / "by_configuration.csv"), "ex02/per_run": table(out / "per_run.csv")})
        for key, value in summary_keys.items():
            run.summary[key] = value
        artifact = wandb.Artifact(f"ex02-{args.model}-results", type="experiment_results",
                                  metadata={"cells": len(cells), "model": args.model})
        for name in ("per_run.csv", "by_configuration.csv", "summary.json", "wandb_runs.json"):
            artifact.add_file(str(out / name), name=f"analysis/{name}")
        for cell in cells:
            prefix = f"{cell['configuration']}/{cell['lesson_id']}"
            for path in cell["files"]:
                artifact.add_file(str(path), name=f"{prefix}/{path.name}")
            with artifact.new_file(f"{prefix}/quality.json", encoding="utf-8") as stream:
                json.dump(cell["quality"], stream, ensure_ascii=False, indent=2)
        run.log_artifact(artifact)
        receipt.update(run_url=run.url, published_at_utc=utcnow())
    finally:
        run.finish()
    receipt["public_verification"] = verify_public(args.entity, args.project, receipt["run_id"], summary_keys)
    write_json(receipt_path, receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
