"""Command-line interface for the SciMKG Ex03 experiment."""
from __future__ import annotations

import argparse
import json
import sys

from experiments.ex01.cli import PAUSED_EXIT, cause_of
from experiments.ex01.client import CodexClient, UsageLimitError
from experiments.ex01.control import BudgetPause, RunBudget
from experiments.ex01.core import utcnow
from experiments.ex01.tracking import ENTITY, PROJECT
from .queries import QUERY_ROOT, build


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    queries = sub.add_parser("queries", help="Freeze the source sentences; --rewrite also asks the model for questions")
    queries.add_argument("--rewrite", action="store_true")
    queries.add_argument("--model", default="gpt-6-luna")
    queries.add_argument("--max-new-calls", type=int, default=None)
    evaluate = sub.add_parser("evaluate", help="Retrieval tables from saved files only")
    evaluate.add_argument("--model", default="gpt-6-luna")
    evaluate.add_argument("--publish", action="store_true", help="Log the tables as one W&B run in the SciMKG project")
    return parser


def queries_command(args):
    client = None
    if args.rewrite:
        from experiments.ex01.core import Journal
        budget = RunBudget(args.max_new_calls, None, QUERY_ROOT / "STOP")
        client = CodexClient(QUERY_ROOT / "cache/llm.jsonl", Journal(QUERY_ROOT), args.model, before_launch=budget.before_launch)
    try:
        saved = build(client)
    except BudgetPause as pause:
        print(f"Ex03 paused: {pause}", file=sys.stderr)
        return PAUSED_EXIT
    except Exception as error:
        limit = cause_of(error, UsageLimitError)
        if limit is None:
            raise
        print(f"Ex03 paused: {limit}", file=sys.stderr)
        return PAUSED_EXIT
    rows = saved["queries"]
    print(json.dumps({"queries": len(rows), "rewritten": sum(bool(r.get("question")) for r in rows),
                      "overlap_flagged": sum(bool(r.get("overlap_flag")) for r in rows)}, indent=2))
    return 0


def publish(result, model):
    import csv
    import wandb
    from experiments.ex01.core import ROOT
    out = result["output"]
    run = wandb.init(entity=ENTITY, project=PROJECT, name=f"ex03-{model}", group=f"ex03-{model}",
                     job_type="segment_retrieval", tags=["Ex03", model], config={"experiment": "Ex03", "model": model,
                     "queries": result["queries"], "rewritten": result["rewritten"]})
    try:
        for name in ("by_method", "per_lesson"):
            with open(ROOT / out / f"{name}.csv", encoding="utf-8") as stream:
                data = list(csv.reader(stream))
            run.log({f"ex03/{name}": wandb.Table(columns=data[0], data=data[1:])})
        artifact = wandb.Artifact(f"ex03-{model}", type="experiment_results")
        artifact.add_dir(str(ROOT / out))
        artifact.add_file(str(QUERY_ROOT / "queries.json"), name="queries.json")
        run.log_artifact(artifact)
        return run.url
    finally:
        run.finish()


def evaluate_command(args):
    from .evaluate import evaluate
    result = evaluate(args.model)
    if args.publish:
        result["wandb_url"] = publish(result, args.model)
        result["published_at_utc"] = utcnow()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    return {"queries": queries_command, "evaluate": evaluate_command}[args.command](args)


def entrypoint():
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Ex03 interrupted; saved queries and cache are preserved.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as error:
        print(f"Ex03 stopped: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1)
