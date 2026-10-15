"""Concept scoring against the author's published lesson labels.

Primary: exact match after NFKC and OpenCC t2s (the pipeline's `concept_normalization`).
Secondary, exploratory: a prediction and a label match when one contains the other and the shorter has at least
two characters. Precision counts predictions, recall counts labels.
"""
from __future__ import annotations

from pathlib import Path

from experiments.ex01.core import digest, normalized_concepts, read_json
from .lessons import DATASET

SCORING = {"gold": "author_published_lesson_labels", "primary": "exact_after_NFKC_OpenCC_t2s",
           "secondary": "substring_min_2_characters_exploratory", "averaging": "per_lesson_then_macro"}


def load_gold(lesson_id, dataset=DATASET):
    dataset = Path(dataset)
    entry = next(e for e in read_json(dataset / "manifest.json")["lessons"] if e["lesson_id"] == lesson_id)
    path = dataset / lesson_id / "evaluation" / "gold.json"
    if digest(path.read_bytes()) != entry["gold"]["sha256"]:
        raise ValueError(f"Gold labels differ from the manifest: {lesson_id}")
    gold = read_json(path)
    if gold["status"] != "frozen" or gold["lesson_id"] != lesson_id:
        raise ValueError(f"Gold labels are not the frozen labels of {lesson_id}")
    return normalized_concepts(gold["concepts"])


def f1(precision, recall):
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def contains(a, b):
    short, long = sorted((a, b), key=len)
    return len(short) >= 2 and short in long


def score(predicted, gold):
    predicted, gold = normalized_concepts(predicted), normalized_concepts(gold)
    hits = sorted(set(predicted) & set(gold))
    precision = len(hits) / len(predicted) if predicted else 0.0
    recall = len(hits) / len(gold)
    loose_p = [p for p in predicted if any(contains(p, g) for g in gold)]
    loose_g = [g for g in gold if any(contains(p, g) for p in predicted)]
    loose_precision = len(loose_p) / len(predicted) if predicted else 0.0
    loose_recall = len(loose_g) / len(gold)
    return {"predicted": len(predicted), "gold": len(gold), "matched": len(hits),
            "precision": precision, "recall": recall, "f1": f1(precision, recall),
            "substring_precision": loose_precision, "substring_recall": loose_recall,
            "substring_f1": f1(loose_precision, loose_recall),
            "matched_concepts": hits, "missed_labels": sorted(set(gold) - set(predicted)),
            "unmatched_predictions": sorted(set(predicted) - set(gold))}


def score_evi(evi, lesson_id, dataset=DATASET):
    """Score the final E/V/I concepts and, as the recall ceiling, the E candidate pool before verification."""
    gold = load_gold(lesson_id, dataset)
    pool = [c for row in evi["segments"] for c in row["candidates"]]
    return {"lesson_id": lesson_id, "scoring": SCORING, "final": score(evi["concepts"], gold),
            "extraction_pool": score(pool, gold)}
