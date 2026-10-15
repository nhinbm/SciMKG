"""Ex03 tables: retrieval quality per lesson, query type and method, from saved files only (no model calls)."""
from __future__ import annotations

import csv
from pathlib import Path
from statistics import mean

from experiments.ex01.core import ROOT, read_json, write_json
from experiments.ex02.lessons import lesson_ids, prepare_lesson
from experiments.ex02.pipeline import CONFIGURATIONS
from experiments.ex02.summary import folder_for
from .queries import QUERY_ROOT
from .retrieval import (BM25, augmented_index, concept_scores, every_mention_index, expected_rank_metrics,
                        first_mention_index, load_run)

ANALYSIS_ROOT = ROOT / "runs/analysis/ex03"
QUERY_TYPES = {"verbatim": "sentence", "rewritten": "question"}
METRICS = ("hit1", "hit3", "mrr", "coverage")


def methods_for(lesson, model):
    """(name, scorer, index or None, source folder) for every method available on this lesson."""
    bm25 = BM25(lesson)
    found = [("random", lambda q: {s["id"]: 0.0 for s in lesson["segments"]}, None, None),
             ("bm25-transcript", bm25.scores, None, None)]
    for configuration in CONFIGURATIONS:
        folder, _ = folder_for(model, configuration, lesson["id"])
        if not (folder / "evi.json").exists():
            continue
        evi, augmentation, events = load_run(folder)
        indexes = {"first": first_mention_index(evi), "every": every_mention_index(evi, lesson)}
        if augmentation is not None:
            indexes["first+A"] = augmented_index(evi, augmentation, events)
        for linking, index in indexes.items():
            found.append((f"graph-{configuration}-{linking}", lambda q, index=index: concept_scores(index, q),
                          index, str(folder.relative_to(ROOT))))
    return found


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(dict.fromkeys(k for r in rows for k in r)))
        writer.writeheader()
        writer.writerows(rows)


def evaluate(model="gpt-6-luna"):
    queries = read_json(QUERY_ROOT / "queries.json")["queries"]
    rows, details = [], []
    for lesson_id in lesson_ids():
        lesson = read_json(prepare_lesson(lesson_id))
        mine = [q for q in queries if q["lesson_id"] == lesson_id]
        for name, scorer, index, source in methods_for(lesson, model):
            for query_type, field in QUERY_TYPES.items():
                usable = [q for q in mine if q.get(field)]
                if not usable:
                    continue
                results = []
                for q in usable:
                    result = expected_rank_metrics(scorer(q[field]), q["segment_id"])
                    results.append(result)
                    details.append({"query_id": q["id"], "query_type": query_type, "method": name, **result})
                rows.append({"lesson_id": lesson_id, "query_type": query_type, "method": name, "queries": len(usable),
                             "segments": len(lesson["segments"]),
                             **{m: round(mean(r[m] for r in results), 4) for m in ("hit1", "hit3", "mrr")},
                             "coverage": round(mean(r["matched"] for r in results), 4),
                             "unreachable_segments": None if index is None else sum(not v for v in index.values()),
                             "index_entries": None if index is None else sum(len(v) for v in index.values()),
                             "source": source})
    by_method = []
    for query_type in QUERY_TYPES:
        for name in dict.fromkeys(r["method"] for r in rows):
            mine = [r for r in rows if r["method"] == name and r["query_type"] == query_type]
            if mine:
                by_method.append({"query_type": query_type, "method": name, "lessons": len(mine),
                                  "queries": sum(r["queries"] for r in mine),
                                  **{f"macro_{m}": round(mean(r[m] for r in mine), 4) for m in METRICS},
                                  "unreachable_segments": None if mine[0]["unreachable_segments"] is None
                                  else sum(r["unreachable_segments"] for r in mine)})
    out = ANALYSIS_ROOT / model
    write_csv(out / "per_lesson.csv", rows)
    write_csv(out / "by_method.csv", by_method)
    write_csv(out / "per_query.csv", details)
    rewritten = [q for q in queries if q.get("question")]
    result = {"model": model, "queries": len(queries), "rewritten": len(rewritten),
              "rewritten_overlap_flagged": sum(q["overlap_flag"] for q in rewritten),
              "lessons_with_all_configurations": sum(
                  all((folder_for(model, c, l)[0] / "evi.json").exists() for c in CONFIGURATIONS) for l in lesson_ids()),
              "by_method": by_method, "output": str(out.relative_to(ROOT))}
    write_json(out / "summary.json", result)
    return result
