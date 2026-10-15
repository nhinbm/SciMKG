"""Pilot: verification (V) on two models, gpt-6-luna and claude-haiku-5-5, giving 10 votes per concept.

Extraction (E) stays on gpt-6-luna. The author's code loops over the models given to Validation, so each
model runs its own rounds; the integration divides by the total votes (model_count * rounds).
Ex01 and Ex02 code is not edited. The pilot writes to a new folder and reuses the saved gpt-6-luna calls
(E and V) from the single-model `full` run, so only the Haiku V calls are new.
"""
from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import shutil
import tempfile
from unittest.mock import patch

from experiments.ex01.author import AuthorLLM
from experiments.ex01.claude_client import ClaudeCliClient
from experiments.ex01.client import CodexClient
from experiments.ex01.core import Journal, ROOT, digest, normalized_concepts, read_json, unique, write_json
from experiments.ex02.scoring import load_gold, score_evi

GPT, HAIKU = "gpt-6-luna", "claude-haiku-5-5"
ALPHA, ROUNDS = 0.7, 5


def pilot_root(effort):
    """One folder per Haiku effort, named after the model and effort, so two runs cannot be confused."""
    return ROOT / "runs/experiments/ex-02-validation" / f"claude-haiku-5-5-effort-{effort}"

# Lessons whose single-model `full` cache already holds the gpt-6-luna E and V calls.
SOURCES = {
    "nervous-system": ROOT / "runs/pipeline/gpt-6-luna/nervous-system",
    "sulfuric-acid-and-sulfate": ROOT / "runs/experiments/ex-02/gpt-6-luna/full/sulfuric-acid-and-sulfate",
}


class RoutedAuthorLLM(AuthorLLM):
    """AuthorLLM whose verification calls use the client of the model the author's loop asked for."""

    def __init__(self, extractor, lesson, validators):
        super().__init__(extractor, lesson)
        self.validators = validators

    def __call__(self, requested_model, prompt):
        is_verification = "Concept Filtering Protocol" in prompt or "Analyze the extracted" in prompt
        client = self.validators[requested_model] if is_verification else self.client
        saved, self.client = self.client, client
        try:
            return super().__call__(requested_model, prompt)
        finally:
            self.client = saved


def run_evi_two_models(lesson, validators, journal, root, rounds=ROUNDS, alpha=ALPHA):
    """E, V and I as in ex01.pipeline.run_evi, with V over every model in `validators` (gpt first)."""
    from ExtractMultimodalConcepts import NER as source
    extractor = validators[GPT]
    root = Path(root)
    models = list(validators)
    total_votes = len(models) * rounds
    source.allEntity.clear(); source.finalEntity.clear()
    adapter = RoutedAuthorLLM(extractor, lesson, validators)
    try:
        with tempfile.TemporaryDirectory(prefix="scimkg-ex02-pilot-") as temporary, patch.object(source, "ner", adapter):
            path = str(Path(temporary) / "lesson.txt")
            Path(path).write_text("\n".join(json.dumps(f"{s['start']}-{s['end']}", ensure_ascii=False) + ": " +
                json.dumps(s["text"], ensure_ascii=False) for s in lesson["segments"]) + "\n", encoding="utf-8")
            with journal.span("E", "fork_extraction"), redirect_stdout(io.StringIO()):
                candidates = source.Extraction(path, [GPT], lesson["subject"], source.allEntity, rounds)
            if len(candidates) != len(lesson["segments"]):
                raise ValueError("Extraction did not process every segment")
            by_time = {f"{s['start']}-{s['end']}": s for s in lesson["segments"]}
            validated, diagnostics = [], []
            for row in candidates:
                adapter.active, adapter.round = by_time[row[0]]["id"], 0
                row[1] = sorted(row[1])
                with journal.span("V", "fork_verification", segment_id=adapter.active), redirect_stdout(io.StringIO()):
                    validated.extend(source.Validation([row], models, lesson["subject"], rounds, path))
                votes = adapter.votes.get(adapter.active, [])
                if row[1] and len(votes) != total_votes:
                    raise ValueError("Verification did not complete every configured round on every model")
                diagnostics.append({"segment_id": adapter.active, "interval": row[0], "candidates": row[1],
                    "raw_extraction": adapter.raw[adapter.active], "votes": votes,
                    "raw_scores": dict(zip(row[1], row[2])), "successful_rounds": len(votes), "failed_rounds": 0})
            with journal.span("I", "fork_integration"), redirect_stdout(io.StringIO()):
                integrated = source.Intergration(validated, rounds, path, model_count=len(models), alpha=alpha)
            accepted = {stamp: unique(terms) for stamp, terms in integrated}
            for diagnostic in diagnostics:
                diagnostic["concepts"] = accepted.get(diagnostic["interval"], [])
                diagnostic["scores"] = {term: (score - 1) / total_votes for term, score in diagnostic["raw_scores"].items()}
            concepts = unique([c for row in diagnostics for c in row["concepts"]])
            result = {"concepts": concepts, "segments": diagnostics, "model": GPT, "validation_models": models,
                      "rounds": rounds, "alpha": alpha,
                      "integration_rule": f"(raw_score-1)/(model_count*rounds), model_count={len(models)}",
                      "extraction_deduplication": "first_occurrence_before_verification"}
            write_json(root / "evi.json", result)
            return result
    finally:
        source.allEntity.clear(); source.finalEntity.clear()


def auc(positives, negatives):
    """Chance that a random positive scores above a random negative (ties count half)."""
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in positives for n in negatives)
    return wins / (len(positives) * len(negatives))


def run_lesson(lesson_id, *, root=None, effort="low"):
    root = Path(root) if root else pilot_root(effort)
    source = SOURCES[lesson_id]
    lesson = read_json(source / "lesson.json")
    if digest(lesson) != read_json(source / "config.json")["lesson_sha256"]:
        raise ValueError(f"lesson.json differs from the one the saved run used: {lesson_id}")
    folder = Path(root) / lesson_id
    cache = folder / "cache/llm.jsonl"
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / "cache/llm.jsonl", cache)
    journal = Journal(folder)
    gpt = CodexClient(cache, journal, GPT)
    haiku = ClaudeCliClient(cache, journal, HAIKU, effort=effort)
    write_json(folder / "pilot_config.json", {"validation_models": [GPT, HAIKU], "haiku_effort": effort,
                                              "gpt_effort": "low", "rounds": ROUNDS, "alpha": ALPHA})
    evi = run_evi_two_models(lesson, {GPT: gpt, HAIKU: haiku}, journal, folder)
    return evi, score_evi(evi, lesson_id)


def summarize(lesson_id, evi, scored, *, root):
    """Scores and the AUC of the total votes for gold versus non-gold candidates in the pool."""
    gold = set(load_gold(lesson_id))
    votes = {}
    for segment in evi["segments"]:
        for term, raw in segment["raw_scores"].items():
            key = normalized_concepts([term])[0] if normalized_concepts([term]) else term
            votes[key] = max(votes.get(key, 0), raw)
    gold_scores = [v for k, v in votes.items() if k in gold]
    other_scores = [v for k, v in votes.items() if k not in gold]
    summary = {"lesson_id": lesson_id, "final": {k: scored["final"][k] for k in ("predicted", "matched", "precision", "recall", "f1")},
               "pool": {k: scored["extraction_pool"][k] for k in ("predicted", "matched", "recall")},
               "auc_total_votes": auc(gold_scores, other_scores) if gold_scores and other_scores else None}
    write_json(Path(root) / lesson_id / "pilot_summary.json", summary)
    return summary


def main(lessons=tuple(SOURCES), *, root=None, effort="low"):
    root = Path(root) if root else pilot_root(effort)
    results = []
    for lesson_id in lessons:
        evi, scored = run_lesson(lesson_id, root=root, effort=effort)
        results.append(summarize(lesson_id, evi, scored, root=root))
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)
    return results


if __name__ == "__main__":
    main()
