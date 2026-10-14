"""Command-line interface for the SciMKG Ex01 experiment."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .client import CodexClient, UsageLimitError
from .control import BudgetPause, RunBudget, StagePause
from .core import ROOT, Journal, append_jsonl, read_json, utcnow
from .resources import ResourceClient
from .tracking import ENTITY, PROJECT, publish_project_public, sync_results, verify_public_results

PREPARATION_ROOT = ROOT / "runs/preprocessing/mooc"
EXPERIMENT_ROOT = ROOT / "runs/pipeline"
# Exit code for "stopped by quota or budget; rerun the same command later". Any other failure exits 1.
PAUSED_EXIT = 75


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    execute = sub.add_parser("run", help="Run the lesson, or continue it from the cache")
    inputs = execute.add_argument_group("Inputs and tracking destination")
    inputs.add_argument("--lesson", type=Path, default=PREPARATION_ROOT / "lesson.json")
    inputs.add_argument("--out", type=Path, help="Run folder; default runs/pipeline/<model>/<lesson>")
    inputs.add_argument("--entity", default=ENTITY)
    inputs.add_argument("--project", default=PROJECT)
    inputs.add_argument("--tracking-mode", choices=("online", "offline", "disabled"), default="online")
    model_settings = execute.add_argument_group("Model settings")
    model_settings.add_argument("--model", default="gpt-6-luna")
    model_settings.add_argument("--rounds", type=int, default=5)
    model_settings.add_argument("--alpha", type=float, default=0.7)
    stops = execute.add_argument_group("Stopping")
    stops.add_argument("--until", choices=("E", "V", "A", "evia", "images", "explanations", "all"), default="all",
                       help="Stop after this stage (evia means A, which includes I). Rerunning continues from the cache.")
    stops.add_argument("--max-new-calls", type=int, default=None,
                       help="Stop before the next request after this many new requests in this invocation; default: no limit")
    stops.add_argument("--max-run-seconds", type=float, default=None,
                       help="Stop before the next request after this many seconds in this invocation; default: no limit")
    recovery = execute.add_argument_group("Recovery options")
    recovery.add_argument("--resume-code-change", action="store_true",
                          help="Resume after a code fix, retaining both source versions; requires saved E/V/I and unchanged client/NER")
    recovery.add_argument("--frozen-sources", action="store_true",
                          help="Reuse saved source receipts, including failures, without new web requests")
    report = sub.add_parser("report", help="Regenerate or sync the report from saved events without model calls")
    report.add_argument("--out", type=Path, required=True)
    report.add_argument("--sync", action="store_true")
    report.add_argument("--verify-public", action="store_true")
    report.add_argument("--publish-public", action="store_true", help="Set the selected project to Public after the run is complete")
    report.add_argument("--entity", default=ENTITY)
    report.add_argument("--project", default=PROJECT)
    return parser


def cause_of(error, kind):
    """The first exception of `kind` in the chain: the author's code re-raises client errors as RuntimeError."""
    seen = set()
    while error is not None and id(error) not in seen:
        if isinstance(error, kind):
            return error
        seen.add(id(error))
        error = error.__cause__ or error.__context__
    return None


def record_batch(folder, started, args, until, reason, hint, code, budget):
    """Append one line per invocation: calls, CLI tokens, the stop reason and any reset time the CLI printed."""
    events = [e for e in Journal(folder).events() if e.get("created_at_utc", "") >= started]
    calls = [e for e in events if e["kind"] == "llm"]
    done = [e for e in calls if e["status"] == "completed"]
    usage = [e.get("usage") or {} for e in done]
    append_jsonl(folder / "batches.jsonl", {
        "started_at_utc": started, "ended_at_utc": utcnow(), "model": args.model, "until": until,
        "reason": reason, "resume_hint": hint, "exit_code": code,
        "calls_launched": len(calls), "calls_completed": len(done), "calls_failed": len(calls) - len(done),
        "input_tokens_cli": sum(u.get("input_tokens") or 0 for u in usage),
        "output_tokens_cli": sum(u.get("output_tokens") or 0 for u in usage),
        "cached_input_tokens_cli": sum(u.get("cached_input_tokens") or 0 for u in usage),
        "max_new_calls": budget.max_calls, "max_run_seconds": budget.max_seconds})


def run_command(args):
    from .pipeline import run
    if not args.lesson.exists() and args.lesson == PREPARATION_ROOT / "lesson.json":
        from .data import prepare
        prepare(PREPARATION_ROOT, Journal(PREPARATION_ROOT), lesson_id="nervous-system")
    identifier = read_json(args.lesson)["id"]
    folder = args.out or EXPERIMENT_ROOT / args.model.replace("/", "-") / identifier
    until = "A" if args.until == "evia" else args.until
    budget = RunBudget(args.max_new_calls, args.max_run_seconds, folder / "STOP")
    started = utcnow()
    reason, hint, code = "failed", None, 1
    try:
        result = run(folder, args.lesson, rounds=args.rounds, alpha=args.alpha, model=args.model, until=until,
                     entity=args.entity, project=args.project, tracking_mode=args.tracking_mode,
                     resume_code_change=args.resume_code_change,
                     client_factory=lambda cache, journal, model: CodexClient(cache, journal, model, before_launch=budget.before_launch),
                     resources_factory=lambda cache, journal: ResourceClient(cache, journal, frozen=args.frozen_sources))
        reason, code = ("completed" if until == "all" else f"stopped_after_{until}"), 0
        print(json.dumps({"output": str(folder), "reason": reason, "cost": result["cost"]}, ensure_ascii=False, indent=2))
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
        record_batch(folder, started, args, until, reason, hint, code, budget)
    if hint:
        print(f"Ex01 paused: {hint}", file=sys.stderr)
    return code


def report_command(args):
    from .report import report_run
    result = sync_results(args.out, args.entity, args.project) if args.sync else report_run(args.out)
    if args.publish_public:
        if not str(result.get("pipeline_status", "")).startswith("completed"):
            raise RuntimeError("The lesson run must be complete before publishing")
        result["tracking_access"] = publish_project_public(args.entity, args.project)
    if args.verify_public:
        result["tracking_access"] = verify_public_results(args.out, args.entity, args.project)
    print(json.dumps({"output": str(args.out / "report.md"), "cost": result["cost"],
                      "public_verification": result.get("tracking_access")}, ensure_ascii=False, indent=2))
    return 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "run":
        return run_command(args)
    return report_command(args)


def entrypoint():
    """Run the CLI and report failures without an unhandled traceback."""
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Ex01 interrupted; recorded results and cache are preserved.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as error:
        print(f"Ex01 stopped: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1)
