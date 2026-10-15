"""Ex02 run of one (configuration, lesson): E, V, I and A with Ex01's code, then concept scoring."""
from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
import tempfile
from unittest.mock import patch

from experiments.ex01.author import AuthorLLM
from experiments.ex01.client import CodexClient
from experiments.ex01.control import BudgetPause, StagePause
from experiments.ex01.core import ROOT, Journal, digest, environment, read_json, revision as ex01_revision, unique, utcnow, write_json
from experiments.ex01.data import validate_lesson
from experiments.ex01.pipeline import expand_concepts, run_evi
from experiments.ex01.tracking import ENTITY, PROJECT, Tracking
from .report import report_run

# Each configuration changes only the number of verification rounds; the threshold stays 0.7.
CONFIGURATIONS = {"full": 5, "one-round": 1, "no-verification": 0}
STAGE_ORDER = ("E", "V", "A")
ALPHA = 0.7


def reached(until, stage):
    return STAGE_ORDER.index(until) <= STAGE_ORDER.index(stage)


def revision():
    """Ex01 code that Ex02 executes, plus Ex02's own files."""
    result = ex01_revision()
    for path in sorted([*Path(__file__).resolve().parent.glob("*.py"), ROOT / "scripts/experiments/ex-02/run.py"]):
        result["source_sha256"][str(path.relative_to(ROOT))] = digest(path.read_bytes())
    return result


def run_extraction(lesson, client, journal, root, until):
    """Verification off: the E candidates are the final concepts, with no V call and no I vote."""
    from ExtractMultimodalConcepts import NER as source
    source.allEntity.clear(); source.finalEntity.clear()
    adapter = AuthorLLM(client, lesson)
    try:
        with tempfile.TemporaryDirectory(prefix="scimkg-ex02-e-") as temporary, patch.object(source, "ner", adapter):
            path = str(Path(temporary) / "lesson.txt")
            Path(path).write_text("\n".join(json.dumps(f"{s['start']}-{s['end']}", ensure_ascii=False) + ": " +
                json.dumps(s["text"], ensure_ascii=False) for s in lesson["segments"]) + "\n", encoding="utf-8")
            # Extraction ignores its round argument; 0 records that no verification follows.
            with journal.span("E", "fork_extraction"), redirect_stdout(io.StringIO()):
                candidates = source.Extraction(path, [client.model], lesson["subject"], source.allEntity, 0)
    finally:
        source.allEntity.clear(); source.finalEntity.clear()
    if len(candidates) != len(lesson["segments"]):
        raise ValueError("Extraction did not process every segment")
    if reached(until, "E"):
        raise StagePause("E")
    journal.record({"kind": "skipped", "stage": "V", "operation": "verification_off", "status": "skipped",
                    "elapsed_seconds": 0})
    by_time = {f"{s['start']}-{s['end']}": s for s in lesson["segments"]}
    segments = [{"segment_id": by_time[stamp]["id"], "interval": stamp, "candidates": sorted(terms),
                 "raw_extraction": adapter.raw[by_time[stamp]["id"]], "votes": [], "concepts": sorted(terms)}
                for stamp, terms, *_ in candidates]
    result = {"concepts": unique(c for row in segments for c in row["concepts"]), "segments": segments,
              "model": client.model, "rounds": 0, "alpha": None, "integration_rule": "none_verification_off",
              "extraction_deduplication": "first_occurrence_before_verification"}
    write_json(Path(root) / "evi.json", result)
    return result


def snapshot_sources(root, source_revision):
    snapshot = Path(root) / "source_snapshot"
    for name, expected in source_revision["source_sha256"].items():
        target = snapshot / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
        if digest(target.read_bytes()) != expected:
            raise ValueError("Source changed while the snapshot was being created")
    write_json(snapshot / "manifest.json", source_revision)


def run(root, lesson_path, *, configuration, model="gpt-6-luna", until="A", tracking_mode="online",
        entity=ENTITY, project=PROJECT, client_factory=CodexClient, tracking_factory=Tracking):
    if configuration not in CONFIGURATIONS:
        raise ValueError(f"Unknown configuration: {configuration}")
    if until not in STAGE_ORDER:
        raise ValueError(f"Invalid stop point: {until}")
    rounds = CONFIGURATIONS[configuration]
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    lesson = read_json(lesson_path)
    validate_lesson(lesson)
    name = f"{model}-{lesson['id']}-{configuration}"
    config = {"experiment": "Ex02", "ex02_protocol": 1, "pipeline_protocol": 3, "configuration": configuration,
        "concept_normalization": "OpenCC-1.4.2-t2s", "lesson_id": lesson["id"], "lesson_sha256": digest(lesson),
        "model": model, "reasoning_effort": "low", "rounds": rounds,
        "verification": "on" if rounds else "off", "alpha": ALPHA if rounds else None,
        "use_conceptnet": True, "use_wikipedia": False, "stages": list(STAGE_ORDER),
        "conceptnet": {"code": "author_conceptExpand", "source": "conceptnet-assertions-5.7.0",
                       "rules": "surface_text_templates"},
        "tracking_entity": entity, "tracking_project": project,
        "tracking_labels": {"experiment": "Ex02", "run_name": name, "group": f"ex02-{model}", "job_type": "concept_quality",
                            "tags": ["Ex02", "subscription", model, lesson["id"], configuration]},
        "source_revision": revision(), "environment": environment(), "quality_review": "author_concept_labels"}
    config_path = root / "config.json"
    if config_path.exists():
        existing = read_json(config_path)
        changed = [k for k, v in config.items() if existing.get(k) != v]
        # The git description changes with every commit; only the hashes of the code decide.
        if "source_revision" in changed and existing["source_revision"]["source_sha256"] == config["source_revision"]["source_sha256"]:
            changed.remove("source_revision")
        if changed:
            raise ValueError(f"Code, data, or configuration changed ({', '.join(changed)}); use a new run folder")
        config = existing
    else:
        config.update(created_at_utc=utcnow(), tracking_mode=tracking_mode)
        write_json(config_path, config)
        write_json(root / "lesson.json", lesson)
        snapshot_sources(root, config["source_revision"])
    journal = Journal(root)
    tracking = tracking_factory(root, config, entity=entity, project=project, mode=tracking_mode)
    journal.listener = tracking.emit
    for event in journal.events():
        try:
            tracking.emit(event)
        except Exception as exc:
            write_json(root / "tracking-pending.json", {"event_id": event["event_id"], "error_type": type(exc).__name__})
    client = client_factory(root / "cache/llm.jsonl", journal, model)
    outcome = "failed"
    try:
        print(f"Ex02: {lesson['id']} {configuration} model={model} until={until}", flush=True)
        with journal.span("pipeline", "lesson_pipeline", lesson_id=lesson["id"], model=model,
                          configuration=configuration, until=until):
            if rounds:
                # Ex01's E/V/I unchanged; its stop points use the same stage names.
                evi = run_evi(lesson, client, journal, root, rounds, ALPHA, until)
            else:
                evi = run_extraction(lesson, client, journal, root, until)
            if reached(until, "V"):
                raise StagePause("V")
            augmentation = expand_concepts(evi, client, journal, lesson["subject"])
            write_json(root / "augmentation.json", augmentation)
            write_json(root / "summary.json", {"lesson_id": lesson["id"], "model": model, "configuration": configuration,
                "pipeline_status": "completed", "evi_concepts": len(evi["concepts"]),
                "added_concepts": len(augmentation["additions"])})
        report = report_run(root)
        tracking.publish_results(report, root)
        if tracking.run is not None:
            for key, value in report["quality_keys"].items():
                tracking.run.summary[key] = value
        outcome = "completed"
    except (StagePause, BudgetPause):
        outcome = "paused"
        raise
    finally:
        journal.listener = None
        try:
            report_run(root)
        finally:
            tracking.finish(failed=outcome == "failed")
    return report_run(root)
