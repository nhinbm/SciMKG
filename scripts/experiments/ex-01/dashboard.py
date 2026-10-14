"""Ex01 dashboard: adds the analysis to the run's W&B record and saves the "Ex01 cost" view.

Run after analyze.py. It writes summary values, tables and one saved view; it never calls a model.
Use --dev to rehearse in a separate project first; the real run is found through tracking.json.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RUN = ROOT / "runs/pipeline/gpt-6-luna/nervous-system"
DEFAULT_ANALYSIS = ROOT / "runs/analysis/ex01/gpt-6-luna"
ENTITY, PROJECT, DEV_PROJECT = "nhinbm-hcmus", "SciMKG", "SciMKG-dev"
SUB_STEP_KEYS = ("E_extraction", "V_feedback", "V_refinement", "A_concept_filter", "explanation_step",
                 "image_call_1", "image_call_2", "image_call_3")
TABLES = {"cost_by_stage": "cost_by_stage.csv", "unit_costs": "unit_costs.csv",
          "price_conversion": "price_conversion.csv", "scenario_author_config": "scenario_author_config.csv"}


def read_csv(path):
    with path.open(encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def slug(text):
    return text.replace(" ", "_").replace(".", "_")


def summary_items(analysis):
    head = json.loads((analysis / "headline.json").read_text(encoding="utf-8"))
    items = {"headline/api_cost_usd": head["api_cost_usd"], "headline/cli_cost_usd": head["cli_cost_usd"],
             "headline/llm_calls": head["llm_calls"], "headline/api_input_tokens": head["api_input_tokens"],
             "headline/api_output_tokens": head["api_output_tokens"],
             "headline/inference_seconds": head["inference_seconds"],
             "headline/dominant_stage_api": head["dominant_stage_api"]}
    for row in read_csv(analysis / "cost_by_stage.csv"):
        key = slug(row["name"])
        items[f"cost/api_usd/{key}"] = float(row["api_cost_usd"])
        items[f"cost/cli_usd/{key}"] = float(row["cli_cost_usd"])
        if row["level"] == "stage":
            items[f"cost/seconds/{key}"] = float(row["stage_wall_seconds"])
    for row in read_csv(analysis / "unit_costs.csv"):
        items[f"unit/{row['key']}/api_usd"] = float(row["api_cost_usd_per_unit"])
        items[f"unit/{row['key']}/api_input_tokens"] = float(row["api_input_tokens_per_unit"])
    for row in read_csv(analysis / "price_conversion.csv"):
        if row["usd_api_like"]:
            items[f"conversion/{slug(row['model'])}/usd"] = float(row["usd_api_like"])
    scenario = [r for r in read_csv(analysis / "scenario_author_config.csv") if r["stage"] == "total"]
    items["scenario/author_config/usd"] = float(scenario[0]["usd"])
    items["scenario/author_config/complete"] = scenario[0]["complete"] == "True"
    return items


def build_view(entity, project, lesson_filter, conversion_keys):
    import wandb_workspaces.reports.v2 as wr
    import wandb_workspaces.workspaces as ws
    summary = [("headline/api_cost_usd", "Chi phí kiểu API (USD)"), ("headline/llm_calls", "Lời gọi thành công"),
               ("headline/api_input_tokens", "Token vào (ước lượng)"), ("headline/api_output_tokens", "Token ra"),
               ("headline/inference_seconds", "Thời gian suy luận (giây)")]
    unit = [("unit/segment/api_usd", "USD mỗi đoạn (E + V)"), ("unit/image/api_usd", "USD mỗi ảnh"),
            ("unit/a_call/api_usd", "USD mỗi lời gọi A"), ("unit/explanation/api_usd", "USD mỗi giải thích")]
    sections = [
        ws.Section(name="Tóm tắt", panels=[wr.ScalarChart(title=t, metric=m) for m, t in summary]),
        ws.Section(name="Tiền đi vào đâu", panels=[wr.BarPlot(
            title="USD theo bước con (kiểu API)", metrics=[f"cost/api_usd/{k}" for k in SUB_STEP_KEYS],
            orientation="v")]),
        ws.Section(name="Đơn giá để mở rộng", panels=[wr.ScalarChart(title=t, metric=m) for m, t in unit]),
        ws.Section(name="Quy đổi theo mô hình", panels=[wr.BarPlot(
            title="USD cho cùng số token (giả định)", metrics=conversion_keys, orientation="v")]),
        ws.Section(name="Tiến trình", panels=[
            wr.LinePlot(title="Lời gọi tích lũy", x="Step", y=["progress/calls"]),
            wr.LinePlot(title="Token CLI tích lũy", x="Step", y=["progress/input_tokens_cli", "progress/output_tokens_cli"])]),
    ]
    return ws.Workspace(entity=entity, project=project, name="Ex01 cost", sections=sections,
                        runset_settings=ws.RunsetSettings(filters=lesson_filter))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--analysis", type=Path, default=DEFAULT_ANALYSIS)
    parser.add_argument("--dev", action="store_true", help=f"rehearse in {DEV_PROJECT} with a new run")
    parser.add_argument("--dry-run", action="store_true", help="print what would be written; no network")
    args = parser.parse_args(argv)
    items = summary_items(args.analysis)
    config = json.loads((args.run / "config.json").read_text(encoding="utf-8"))
    lesson_filter = f"Config('lesson_id') = {config['lesson_id']!r}"
    conversion_keys = [k for k in items if k.startswith("conversion/")]
    if args.dry_run:
        print(json.dumps({"summary_keys": sorted(items), "tables": sorted(TABLES),
                          "view_sections": ["Tóm tắt", "Tiền đi vào đâu", "Đơn giá để mở rộng",
                                            "Quy đổi theo mô hình", "Tiến trình"],
                          "conversion_metrics": conversion_keys}, ensure_ascii=False, indent=2))
        return 0
    import wandb
    project = DEV_PROJECT if args.dev else PROJECT
    if args.dev:
        run = wandb.init(entity=ENTITY, project=project, name=f"dev-{config['model']}-{config['lesson_id']}",
                         job_type="dashboard_rehearsal", config=config)
    else:
        tracking = json.loads((args.run / "tracking.json").read_text(encoding="utf-8"))
        run = wandb.init(entity=ENTITY, project=project, id=tracking["run_id"], resume="must")
    run.summary.update(items)
    for name, file in TABLES.items():
        rows = read_csv(args.analysis / file)
        columns = list(rows[0])
        run.log({f"analysis/{name}": wandb.Table(columns=columns, data=[[r[c] for c in columns] for r in rows])})
    run.finish()
    view = build_view(ENTITY, project, lesson_filter, conversion_keys)
    view.save()
    print(json.dumps({"project": project, "run": run.url if hasattr(run, "url") else None, "view": view.url},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    main()
