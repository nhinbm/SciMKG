#!/usr/bin/env python3
"""Add bar charts to an existing Ex02 or Ex03 summary run, so its Charts tab shows the results.

The run is resumed by id, so no new run is created and no existing data is removed.
The numbers come from the CSV tables already written under runs/analysis/; no model is called.
Use --dry-run to print the charts without logging anything.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from experiments.ex01.tracking import ENTITY, PROJECT  # noqa: E402

RUNS = {
    "ex02": {"run_id": "ex02-8319b815", "folder": ROOT / "runs/analysis/ex02/gpt-6-luna"},
    "ex03": {"run_id": "krpbt4zl", "folder": ROOT / "runs/analysis/ex03/gpt-6-luna"},
}


def read_rows(path):
    with open(path, encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def bar_rows(rows, label, value):
    return [[label(row), float(row[value])] for row in rows]


def ex02_charts(folder):
    per_run = read_rows(folder / "per_run.csv")
    by_config = read_rows(folder / "by_configuration.csv")
    return {
        "F1 theo bài và cấu hình": (
            bar_rows(per_run, lambda r: f"{r['lesson_id']} / {r['configuration']}", "f1")),
        "Precision trung bình sáu bài": bar_rows(by_config, lambda r: r["configuration"], "macro_precision"),
        "Recall trung bình sáu bài": bar_rows(by_config, lambda r: r["configuration"], "macro_recall"),
        "F1 trung bình sáu bài": bar_rows(by_config, lambda r: r["configuration"], "macro_f1"),
        "Chi phí kiểu API (USD, sáu bài)": bar_rows(by_config, lambda r: r["configuration"], "api_cost_usd"),
    }


def ex03_charts(folder):
    rows = read_rows(folder / "by_method.csv")
    charts = {}
    for query_type, title in (("verbatim", "Hit@1 truy vấn nguyên văn (309 câu)"),
                              ("rewritten", "Hit@1 truy vấn viết lại (309 câu)")):
        picked = [r for r in rows if r["query_type"] == query_type]
        charts[title] = bar_rows(picked, lambda r: r["method"], "macro_hit1")
    return charts


def publish(name, charts, dry_run):
    import wandb
    print(f"[{name}] run {RUNS[name]['run_id']}")
    for title, rows in charts.items():
        print(f"  {title}")
        for label, value in rows:
            print(f"    {label:45s} {value:.4f}")
    if dry_run:
        return
    run = wandb.init(entity=ENTITY, project=PROJECT, id=RUNS[name]["run_id"], resume="must")
    try:
        payload = {}
        for title, rows in charts.items():
            table = wandb.Table(columns=["label", "value"], data=rows)
            payload[f"charts/{name}/{title}"] = wandb.plot.bar(table, "label", "value", title=title)
        run.log(payload)
    finally:
        run.finish()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", choices=sorted(RUNS) + ["all"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    names = sorted(RUNS) if args.run == "all" else [args.run]
    builders = {"ex02": ex02_charts, "ex03": ex03_charts}
    for name in names:
        publish(name, builders[name](RUNS[name]["folder"]), args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
