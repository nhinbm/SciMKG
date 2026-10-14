"""Ex01 measurement pipeline that runs the author's SciMKG functions with Ex01 clients."""
from __future__ import annotations

from contextlib import ExitStack, redirect_stdout
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from unittest.mock import patch

from .author import AuthorLLM, image_prompt, wikipedia_lookup
from .client import CodexClient, CONCEPTS
from .conceptnet import LocalConceptNet, ensure_index, surface_rules
from .control import BudgetPause, StagePause
from .core import Journal, ROOT, digest, environment, normalized_concepts, read_json, revision, unique, utcnow, write_json
from .data import extract_clips, validate_lesson
from .report import report_run
from .resources import ResourceClient, snapshot_prices
from .tracking import ENTITY, PROJECT, Tracking

# Stop points in the order the pipeline reaches them. `I` runs together with `V` (no LLM call).
STAGE_ORDER = ("E", "V", "A", "images", "explanations", "all")


def reached(until, stage):
    """True when the requested stop point is at or before `stage`; `all` never stops early."""
    return until != "all" and STAGE_ORDER.index(until) <= STAGE_ORDER.index(stage)


def run_evi(lesson, client, journal, root, rounds, alpha, until):
    from ExtractMultimodalConcepts import NER as source
    root = Path(root)
    source.allEntity.clear(); source.finalEntity.clear()
    adapter = AuthorLLM(client, lesson)
    try:
        with tempfile.TemporaryDirectory(prefix="scimkg-ex01-evi-") as temporary, patch.object(source, "ner", adapter):
            path = str(Path(temporary) / "lesson.txt")
            Path(path).write_text("\n".join(json.dumps(f"{s['start']}-{s['end']}", ensure_ascii=False) + ": " +
                json.dumps(s["text"], ensure_ascii=False) for s in lesson["segments"]) + "\n", encoding="utf-8")
            with journal.span("E", "fork_extraction"), redirect_stdout(io.StringIO()):
                candidates = source.Extraction(path, [client.model], lesson["subject"], source.allEntity, rounds)
            if len(candidates) != len(lesson["segments"]):
                raise ValueError("Extraction did not process every segment")
            if reached(until, "E"):
                raise StagePause("E")
            by_time = {f"{s['start']}-{s['end']}": s for s in lesson["segments"]}
            validated, diagnostics = [], []
            for row in candidates:
                adapter.active, adapter.round = by_time[row[0]]["id"], 0
                # Persist stable concept/score associations rather than set iteration order.
                row[1] = sorted(row[1])
                with journal.span("V", "fork_verification", segment_id=adapter.active), redirect_stdout(io.StringIO()):
                    validated.extend(source.Validation([row], [client.model], lesson["subject"], rounds, path))
                votes = adapter.votes.get(adapter.active, [])
                if row[1] and len(votes) != rounds:
                    raise ValueError("Verification did not complete every configured round")
                diagnostics.append({"segment_id": adapter.active, "interval": row[0], "candidates": row[1],
                    "raw_extraction": adapter.raw[adapter.active], "votes": votes,
                    "raw_scores": dict(zip(row[1], row[2])), "successful_rounds": len(votes), "failed_rounds": 0})
            with journal.span("I", "fork_integration"), redirect_stdout(io.StringIO()):
                integrated = source.Intergration(validated, rounds, path, model_count=1, alpha=alpha)
            accepted = {stamp: unique(terms) for stamp, terms in integrated}
            for diagnostic in diagnostics:
                diagnostic["concepts"] = accepted.get(diagnostic["interval"], [])
                diagnostic["scores"] = {term: (score - 1) / rounds for term, score in diagnostic["raw_scores"].items()}
            concepts = unique([c for row in diagnostics for c in row["concepts"]])
            result = {"concepts": concepts, "segments": diagnostics, "model": client.model, "rounds": rounds,
                      "alpha": alpha, "integration_rule": "(raw_score-1)/(model_count*rounds)",
                      "extraction_deduplication": "first_occurrence_before_verification"}
            write_json(root / "evi.json", result)
            return result
    finally:
        source.allEntity.clear(); source.finalEntity.clear()


def expand_concepts(evi, client, journal, subject):
    """Run NER.conceptExpand with the surface-text rules, which the released code leaves empty."""
    from ExtractMultimodalConcepts import NER as source, ConceptNet
    lookup = LocalConceptNet(ensure_index(journal), journal)
    adapter = AuthorLLM(client)
    adapter.conceptnet = lookup
    # Rebuild the author's module state as Extraction and Integration left it.
    source.allEntity.clear(); source.finalEntity.clear()
    source.allEntity.update(c for row in evi["segments"] for c in row["candidates"])
    source.finalEntity.update(evi["concepts"])
    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(source, "ner", adapter))
            stack.enter_context(patch.object(ConceptNet, "requests", lookup))
            stack.enter_context(patch.object(ConceptNet, "extract_cell_nouns", surface_rules(lookup)))
            with journal.span("A", "author_concept_expand"), redirect_stdout(io.StringIO()):
                found = source.conceptExpand(subject)
    finally:
        lookup.close()
        source.allEntity.clear(); source.finalEntity.clear()
    existing = set(normalized_concepts(evi["concepts"]))
    return {"additions": [c for c in normalized_concepts(found) if c not in existing],
            "raw_additions": unique(found), "status": "completed",
            "source": {"dump": lookup.meta["dump_url"], "sha256": lookup.meta["dump_sha256"]},
            "implementation": "author_conceptExpand_surface_rules"}


def align_images(lesson, concepts, client, journal):
    links = []
    with journal.span("image_alignment", "author_image_analysis"):
        for image in lesson["images"]:
            prompt = image_prompt(image["path"], lesson["subject"], concepts)
            terms = []
            # mainImages unions three answers per image.
            for round_index in range(3):
                answer = client.call("image_alignment", prompt, CONCEPTS, image=image["path"],
                                     task=f"image/{image['id']}", round_index=round_index)
                terms += answer["concepts"]
            links.append({"image_id": image["id"], "image_sha256": image["sha256"], "path": image["path"],
                          "concepts": normalized_concepts(terms),
                          "method": "author_prompt_three_calls_union", "quality_review": "not_measured"})
    return links


def explain(concepts, client, resources, journal, subject):
    from ExtractMultimodalConcepts import NER as source, Wikipediaapi_model
    adapter = AuthorLLM(client)
    adapter.concepts = tuple(concepts)
    evidence = {}
    source.finalEntity.clear()
    source.finalEntity.update(concepts)
    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(source, "ner", adapter))
            stack.enter_context(patch.object(Wikipediaapi_model, "get_wikipedia_summary",
                                             wikipedia_lookup(resources, evidence)))
            with journal.span("explanation", "author_expand_explanations"), redirect_stdout(io.StringIO()):
                pairs = source.expandExplanations(subject, use_conceptnet=False, use_wikipedia=True)
    finally:
        source.finalEntity.clear()
    return {concept: {"text": text, "grounded": evidence[concept]["grounded"], "source": evidence[concept],
                      "quality_review": "not_measured"} for concept, text in pairs}


def synthesize(payload, target, journal, executor, probe):
    """One TTS attempt loop; every attempt is journaled, and a success returns the file's hash and duration."""
    last_error = None
    for attempt in range(1, 4):
        start, stamp = time.monotonic(), utcnow()
        try:
            with tempfile.TemporaryDirectory(prefix="scimkg-ex01-speech-") as tmp:
                text = Path(tmp) / "text.txt"
                text.write_text(payload["text"], encoding="utf-8")
                aiff = Path(tmp) / "speech.aiff"
                executor(["say", "-v", "Tingting", "-f", str(text), "-o", str(aiff)], check=True,
                         capture_output=True, timeout=180)
                executor(["ffmpeg", "-y", "-v", "error", "-i", str(aiff), "-ar", "22050", str(target)],
                         check=True, capture_output=True, timeout=180)
            saved = {"sha256": digest(target.read_bytes()), "duration_seconds": probe(target)}
            status, last_error = "completed", None
        except Exception as exc:
            status, last_error = "failed", exc
        event = journal.record({"kind": "local", "stage": "audio", "operation": "tts",
            "status": status, "attempt": attempt, "retry": attempt > 1,
            "started_at_utc": stamp, "ended_at_utc": utcnow(), "elapsed_seconds": time.monotonic() - start,
            "api_paid_usd": 0, "character_count": len(payload["text"]), "inputs": payload,
            "output": saved if last_error is None else None, "error": str(last_error)[:300] if last_error else None})
        if last_error is None:
            return {**saved, "event_id": event["event_id"]}
        if attempt < 3:
            time.sleep(2 ** attempt)
    raise last_error


def speech(explanations, folder, journal, previous=None, *, executor=subprocess.run):
    """One WAV per concept in the run folder. `previous` is the saved index: finished audio is reused, not synthesised again."""
    from .data import probe
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    previous = previous or {}
    out = {}
    with journal.span("audio", "local_tingting_tts"):
        for concept, explanation in explanations.items():
            payload = {"text": explanation["text"], "voice": "Tingting", "sample_rate": 22050, "format": "wav"}
            payload_sha = digest(payload)
            target = folder / f"{digest(concept)[:16]}.wav"
            saved = previous.get(concept)
            if saved and saved["payload_sha256"] == payload_sha and target.exists() and digest(target.read_bytes()) == saved["sha256"]:
                journal.record({"kind": "cache", "stage": "audio", "operation": "tts_cache", "status": "completed",
                                "elapsed_seconds": 0, "origin_event_ids": [saved["event_id"]]})
            else:
                saved = synthesize(payload, target, journal, executor, probe)
            out[concept] = {"path": str(target.resolve()), "sha256": saved["sha256"],
                            "duration_seconds": saved["duration_seconds"], "character_count": len(payload["text"]),
                            "voice": "Tingting", "payload_sha256": payload_sha, "event_id": saved["event_id"],
                            "quality_review": "not_measured"}
    return out


def align_video(lesson, evi, folder, journal):
    with journal.span("video_alignment", "timestamp_alignment") as state:
        if not lesson.get("video"):
            state["status"] = "not_measured"
            journal.record({"kind": "missing", "stage": "video_alignment", "operation": "original_video_missing",
                            "status": "not_measured", "elapsed_seconds": 0})
            return {"status": "not_measured", "reason": "verified_original_video_missing", "timestamp_links": evi["segments"]}
        video = lesson["video"]
        if video.get("clip_start_seconds", 0) != 0:
            raise ValueError("Ex01 clip extraction requires the full video starting at timestamp zero")
        clips = extract_clips(video["path"], lesson["segments"], Path(folder) / "clips")
        return {"status": "completed", "source_url": video["source_url"], "source_sha256": video["sha256"], "clips": clips,
                "timestamp_links": evi["segments"], "semantic_quality": "not_measured"}


def export_graph(evi, images, explanations, audio, video, folder, journal):
    """Write triples in the author's GeneratorTriples vocabulary, then RDF with RDF/rdf.py."""
    from RDF.rdf import TriplesToRDF
    folder = Path(folder)
    with journal.span("export", "author_triples_to_rdf"):
        triples = []
        for concept, explanation in explanations.items():
            triples += [[concept, "has an explanation", explanation["text"]],
                        [explanation["text"], "is an explanationof", concept]]
            if concept in audio:
                name = Path(audio[concept]["path"]).name
                triples += [[concept, "has an audio", name], [name, "is an audio of", concept]]
        for image in images:
            name = Path(image["path"]).name
            triples += [x for concept in image["concepts"] if concept in explanations
                        for x in ([concept, "has an image", name], [name, "is an image of", concept])]
        if video["status"] == "completed":
            clips = {clip["segment_id"]: Path(clip["path"]).name for clip in video["clips"]}
            for row in evi["segments"]:
                for concept in normalized_concepts(row["concepts"]):
                    if concept in explanations and row["segment_id"] in clips:
                        clip = clips[row["segment_id"]]
                        triples += [[concept, "has a video", clip], [clip, "is a video of", concept]]
        write_json(folder / "triples.json", triples)
        converter, log = TriplesToRDF(), io.StringIO()
        with redirect_stdout(log):
            converter.convert_triples_to_rdf(triples)
            converter.save_rdf(str(folder / "graph.ttl"))
        # TriplesToRDF reports skipped triples and save errors only by printing them.
        if "警告：" in log.getvalue() or "错误：" in log.getvalue():
            raise ValueError("RDF conversion skipped triples or failed to save:\n" + log.getvalue()[-500:])
        return {"triples": len(triples), "rdf_triples": len(converter.graph)}


def run(root, lesson_path, *, rounds=5, alpha=0.7, model="gpt-6-luna", until="all", tracking_mode="online",
        entity=ENTITY, project=PROJECT, client_factory=CodexClient, resources_factory=ResourceClient,
        tracking_factory=Tracking, speech_function=speech, resume_code_change=False):
    if rounds <= 0 or not 0 <= alpha <= 1:
        raise ValueError("Invalid round count or threshold")
    if until not in STAGE_ORDER:
        raise ValueError(f"Invalid stop point: {until}")
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    lesson = read_json(lesson_path)
    validate_lesson(lesson)
    configuration = {"pipeline_protocol": 3, "concept_normalization": "OpenCC-1.4.2-t2s",
        "lesson_id": lesson["id"], "lesson_sha256": digest(lesson), "model": model,
        "reasoning_effort": "low", "rounds": rounds, "alpha": alpha, "use_conceptnet": True, "use_wikipedia": True,
        "image_rounds": 3, "image_candidates": "evi_concepts",
        "conceptnet": {"code": "author_conceptExpand", "source": "conceptnet-assertions-5.7.0",
                       "rules": "surface_text_templates"},
        "tts": {"backend": "local_say", "voice": "Tingting"}, "tracking_entity": entity, "tracking_project": project,
        "source_revision": revision(), "environment": environment(), "quality_review": "not_measured_in_ex01"}
    config_path = root / "config.json"
    transition = None
    if config_path.exists():
        existing = read_json(config_path)
        changed = [k for k, v in configuration.items() if existing.get(k) != v]
        # The git description changes with every commit; only the hashes of the code decide.
        if "source_revision" in changed and existing["source_revision"]["source_sha256"] == configuration["source_revision"]["source_sha256"]:
            changed.remove("source_revision")
        if changed == ["source_revision"] and resume_code_change:
            if not (root / "evi.json").exists():
                raise ValueError("Code-change recovery requires a complete saved E/V/I result")
            previous, updated = existing["source_revision"], configuration["source_revision"]
            for name in ("experiments/ex01/client.py", "experiments/ex01/author.py", "ExtractMultimodalConcepts/NER.py"):
                if previous["source_sha256"].get(name) != updated["source_sha256"].get(name):
                    raise ValueError("E/V/I inference code changed; a new run is required")
            previous_count = len(Journal(root).events())
            history = existing.get("source_versions", [{"fingerprint": digest(previous), "revision": previous,
                "effective_at_utc": existing["created_at_utc"], "event_boundary": 0,
                "snapshot_directory": "source_snapshot"}])
            # The original snapshot must survive an explicit recovery with corrected code.
            original = root / "source_snapshot"
            if not original.exists():
                original.mkdir(parents=True)
                for name, expected in previous["source_sha256"].items():
                    source = ROOT / name
                    if digest(source.read_bytes()) != expected:
                        raise ValueError("Previous source snapshot is missing; run history cannot be rewritten")
                    target = original / name; target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
                write_json(original / "manifest.json", previous)
            if not (original / "config.json").exists():
                write_json(original / "config.json", existing)
            directory = "source_snapshots/" + digest(updated)[:16]
            for name, expected in updated["source_sha256"].items():
                target = root / directory / name; target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, target)
                if digest(target.read_bytes()) != expected:
                    raise ValueError("Source changed while the snapshot was being created")
            write_json(root / directory / "manifest.json", updated)
            history = [*history, {"fingerprint": digest(updated), "revision": updated,
                "effective_at_utc": utcnow(), "event_boundary": previous_count, "snapshot_directory": directory}]
            existing.update(source_revision=updated, source_versions=history)
            write_json(config_path, existing)
            transition = {"kind": "recovery", "stage": "preprocessing", "operation": "explicit_resume_code_change",
                          "status": "completed", "elapsed_seconds": 0, "source_versions": history}
        elif changed:
            raise ValueError("Code, data, or configuration changed; use --out for a new run folder to preserve history")
        configuration = existing
    else:
        configuration.update(created_at_utc=utcnow(), tracking_mode=tracking_mode)
        write_json(config_path, configuration)
        write_json(root / "lesson.json", lesson)
        snapshot = root / "source_snapshot"
        for name, expected in configuration["source_revision"]["source_sha256"].items():
            target = snapshot / name; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
            if digest(target.read_bytes()) != expected:
                raise ValueError("Source changed while the snapshot was being created")
        write_json(snapshot / "manifest.json", configuration["source_revision"])
        write_json(snapshot / "config.json", configuration)
    journal = Journal(root)
    if transition:
        journal.record(transition)
    preparation_path = lesson.get("preparation_journal")
    if preparation_path and Path(preparation_path).exists():
        imported = {e["event_id"] for e in journal.events()}
        for event in Journal(Path(preparation_path).parent).events():
            if event["event_id"] not in imported:
                journal.record({**event, "origin_preparation_journal": preparation_path})
    resources = resources_factory(root / "cache/resources.jsonl", journal)
    snapshot_prices(root, resources, model)
    tracking = tracking_factory(root, configuration, entity=entity, project=project, mode=tracking_mode)
    journal.listener = tracking.emit
    for event in journal.events():
        try:
            tracking.emit(event)
        except Exception as exc:
            write_json(root / "tracking-pending.json", {"event_id": event["event_id"], "error_type": type(exc).__name__})
    client = client_factory(root / "cache/llm.jsonl", journal, model)
    outcome = "failed"
    try:
        print(f"Ex01: {lesson['id']} model={model} until={until}", flush=True)
        with journal.span("pipeline", "lesson_pipeline", lesson_id=lesson["id"], model=model, until=until):
            with journal.span("preprocessing", "check_prepared_inputs") as state:
                state["status"] = "not_measured"
                journal.record({"kind": "missing", "stage": "preprocessing", "operation": "historical_preprocessing",
                                "status": "not_measured", "elapsed_seconds": 0})
            evi = run_evi(lesson, client, journal, root, rounds, alpha, until)
            if reached(until, "V"):
                raise StagePause("V")
            augmentation = expand_concepts(evi, client, journal, lesson["subject"])
            write_json(root / "augmentation.json", augmentation)
            if reached(until, "A"):
                raise StagePause("A")
            images = align_images(lesson, evi["concepts"], client, journal)
            write_json(root / "images.json", images)
            if reached(until, "images"):
                raise StagePause("images")
            # mainImages offers only the integrated E/V/I concepts as image candidates.
            concepts = normalized_concepts(evi["concepts"] + augmentation["additions"] +
                                           [c for image in images for c in image["concepts"]])
            explanations = explain(concepts, client, resources, journal, lesson["subject"])
            write_json(root / "explanations.json", explanations)
            if reached(until, "explanations"):
                raise StagePause("explanations")
            previous_audio = read_json(root / "audio.json") if (root / "audio.json").exists() else {}
            audio = speech_function(explanations, root / "audio", journal, previous=previous_audio)
            write_json(root / "audio.json", audio)
            video = align_video(lesson, evi, root, journal)
            write_json(root / "video.json", video)
            graph = export_graph(evi, images, explanations, audio, video, root, journal)
            summary = {"lesson_id": lesson["id"], "model": model,
                "pipeline_status": "completed_with_missing_resources" if lesson["missing_resources"] else "completed",
                "evi_concepts": len(evi["concepts"]), "added_concepts": len(augmentation["additions"]),
                "image_concepts": len(concepts), "explanations": len(explanations), "audio_files": len(audio),
                "ungrounded_explanations": sum(not e["grounded"] for e in explanations.values()), **graph}
            summary["stage_status"] = {"E": "completed", "V": "completed", "I": "completed", "A": "completed",
                "image_alignment": "completed", "explanation": "completed", "audio": "completed",
                "video_alignment": video["status"], "export": "completed"}
            write_json(root / "summary.json", summary)
        report = report_run(root)
        tracking.publish_results(report, root)
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
