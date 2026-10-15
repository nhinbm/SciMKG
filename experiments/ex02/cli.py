"""Command-line interface for the SciMKG Ex02 experiment."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from experiments.ex01.cli import PAUSED_EXIT, cause_of, record_batch
from experiments.ex01.client import CodexClient, UsageLimitError
from experiments.ex01.control import BudgetPause, RunBudget, StagePause
from experiments.ex01.core import ROOT, Journal, read_json, utcnow
from experiments.ex01.tracking import ENTITY, PROJECT, Tracking
from .lessons import lesson_ids, prepare_lesson
from .pipeline import CONFIGURATIONS, STAGE_ORDER

EXPERIMENT_ROOT = ROOT / "runs/experiments/ex-02"


def run_folder(model, configuration, lesson_id):
    return EXPERIMENT_ROOT / model.replace("/", "-") / configuration / lesson_id


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    execute = sub.add_parser("run", help="Run one (configuration, lesson), or continue it from the cache")
    execute.add_argument("--lesson", required=True, choices=lesson_ids())
    execute.add_argument("--config", required=True, choices=tuple(CONFIGURATIONS))
    execute.add_argument("--model", default="gpt-6-luna")
    execute.add_argument("--until", choices=STAGE_ORDER, default="A",
                         help="Stop after this stage (V includes I). Rerunning continues from the cache.")
    execute.add_argument("--out", type=Path, help="Run folder; default runs/experiments/ex-02/<model>/<config>/<lesson>")
    execute.add_argument("--entity", default=ENTITY)
    execute.add_argument("--project", default=PROJECT)
    execute.add_argument("--tracking-mode", choices=("online", "offline", "disabled"), default="online")
    execute.add_argument("--max-new-calls", type=int, default=None,
                         help="Stop before the next request after this many new requests in this invocation")
    execute.add_argument("--max-run-seconds", type=float, default=None,
                         help="Stop before the next request after this many seconds in this invocation")
    report = sub.add_parser("report", help="Recompute cost and quality of a run folder without model calls")
    report.add_argument("--out", type=Path, required=True)
    report.add_argument("--sync", action="store_true", help="Also upload the saved events and results to W&B")
    summary = sub.add_parser("summary", help="Tables across all Ex02 runs, from saved files only")
    summary.add_argument("--model", default="gpt-6-luna")
    return parser


def run_command(args):
    from .pipeline import run
    lesson = prepare_lesson(args.lesson)
    folder = args.out or run_folder(args.model, args.config, args.lesson)
    budget = RunBudget(args.max_new_calls, args.max_run_seconds, folder / "STOP")
    started = utcnow()
    reason, hint, code = "failed", None, 1
    try:
        result = run(folder, lesson, configuration=args.config, model=args.model, until=args.until,
                     entity=args.entity, project=args.project, tracking_mode=args.tracking_mode,
                     client_factory=lambda cache, journal, model: CodexClient(cache, journal, model, before_launch=budget.before_launch))
        reason, code = ("completed" if args.until == "A" else f"stopped_after_{args.until}"), 0
        print(json.dumps({"output": str(folder), "reason": reason, "quality": result["quality"]["final"]},
                         ensure_ascii=False, indent=2))
    except StagePause as pause:
        reason, code = f"stopped_after_{pause.stage}", 0
    except BudgetPause as pause:
        reason, hint, code = "budget_pause", str(pause), PAUSED_EXIT
    except KeyboardInterrupt:
        reason, code = "interrupted", 130
        raise
    except Exception as error:
        limit = cause_of(error, UsageLimitError)
        if limit is None:
            raise
        reason, hint, code = "usage_limit", str(limit), PAUSED_EXIT
    finally:
        if folder.exists():
            record_batch(folder, started, args, args.until, reason, hint, code, budget)
    if hint:
        print(f"Ex02 paused: {hint}", file=sys.stderr)
    return code


def report_command(args):
    from .report import report_run
    result = report_run(args.out)
    if args.sync:
        config = read_json(args.out / "config.json")
        tracking = Tracking(args.out, config, entity=config["tracking_entity"], project=config["tracking_project"], mode="online")
        try:
            for event in Journal(args.out).events():
                tracking.emit(event)
            tracking.publish_results(result, args.out)
            for key, value in result["quality_keys"].items():
                tracking.run.summary[key] = value
        finally:
            tracking.finish()
    print(json.dumps({"output": str(args.out / "report.md"), "quality": result["quality"]}, ensure_ascii=False, indent=2))
    return 0


def summary_command(args):
    from .summary import summarize
    print(json.dumps(summarize(args.model), ensure_ascii=False, indent=2))
    return 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    return {"run": run_command, "report": report_command, "summary": summary_command}[args.command](args)


def entrypoint():
    """Run the CLI and report failures without an unhandled traceback."""
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Ex02 interrupted; recorded results and cache are preserved.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as error:
        print(f"Ex02 stopped: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1)
