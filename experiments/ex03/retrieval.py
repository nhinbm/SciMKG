"""Segment retrieval with concept indexes from the Ex02 graphs, a full-text BM25 reference and random ranking.

Scores are exact expectations under random tie-breaking, so results do not depend on a seed:
a query that matches nothing ranks every segment equally and scores as random.
"""
from __future__ import annotations

from collections import Counter
import json
import math
import re

from experiments.ex01.core import normalize_concept, normalized_concepts, read_json

MIN_CONCEPT_CHARACTERS = 2


def clean(text):
    return re.sub(r"[\W_]+", "", normalize_concept(text))


def usable(concepts):
    # Single characters match almost any sentence; Ex02's substring rule uses the same floor.
    return {c for c in normalized_concepts(concepts) if len(c) >= MIN_CONCEPT_CHARACTERS}


def first_mention_index(evi):
    """The author's linking: each concept sits on the first segment it was extracted from."""
    return {row["segment_id"]: usable(row["concepts"]) for row in evi["segments"]}


def every_mention_index(evi, lesson):
    """Each graph concept sits on every segment whose transcript contains it."""
    concepts = usable(evi["concepts"])
    return {s["id"]: {c for c in concepts if c in clean(s["text"])} for s in lesson["segments"]}


def augmented_index(evi, augmentation, events):
    """First-mention index plus A's additions, placed on the segment of the seed concept they came from."""
    index = first_mention_index(evi)
    home = {c: sid for sid, concepts in index.items() for c in concepts}
    added = set(normalized_concepts(augmentation["additions"]))
    for event in events:
        if event.get("kind") != "llm" or event.get("stage") != "A" or event.get("status") != "completed":
            continue
        seed = normalize_concept(event["task"].split("/", 1)[1])
        if seed not in home:
            continue
        for term in normalized_concepts(t.lstrip("-").strip() for t in event["output"]["concepts"]):
            if term in added and len(term) >= MIN_CONCEPT_CHARACTERS:
                index[home[seed]].add(term)
    return index


def concept_scores(index, query):
    """IDF-weighted count of the segment's concepts that occur in the query."""
    text = clean(query)
    df = Counter(c for concepts in index.values() for c in concepts)
    n = len(index)
    # fsum: the same terms give the same float in any order, so equal scores stay equal across processes.
    return {sid: math.fsum(math.log(1 + (n - df[c] + 0.5) / (df[c] + 0.5)) for c in concepts if c in text)
            for sid, concepts in index.items()}


class BM25:
    """Character-bigram BM25 over segment transcripts (Chinese has no spaces)."""
    def __init__(self, lesson, k1=1.2, b=0.75):
        self.k1, self.b = k1, b
        self.docs = {s["id"]: Counter(self.grams(s["text"])) for s in lesson["segments"]}
        self.length = {sid: sum(d.values()) for sid, d in self.docs.items()}
        self.mean = sum(self.length.values()) / len(self.docs)
        self.df = Counter(g for d in self.docs.values() for g in d)

    @staticmethod
    def grams(text):
        text = clean(text)
        return [text[i:i + 2] for i in range(len(text) - 1)]

    def scores(self, query):
        n, result = len(self.docs), {}
        terms = set(self.grams(query))
        for sid, doc in self.docs.items():
            norm = self.k1 * (1 - self.b + self.b * self.length[sid] / self.mean)
            result[sid] = math.fsum(math.log(1 + (n - self.df[g] + 0.5) / (self.df[g] + 0.5)) *
                                    doc[g] * (self.k1 + 1) / (doc[g] + norm) for g in terms if g in doc)
        return result


def expected_rank_metrics(scores, answer):
    """Hit@1, Hit@3 and reciprocal rank of the answer, averaged over the orders random tie-breaking allows."""
    mine = scores[answer]
    higher = sum(v > mine for v in scores.values())
    tied = sum(v == mine for v in scores.values())  # includes the answer
    positions = range(higher + 1, higher + tied + 1)
    return {"hit1": sum(p <= 1 for p in positions) / tied, "hit3": sum(p <= 3 for p in positions) / tied,
            "mrr": sum(1 / p for p in positions) / tied, "matched": any(v > 0 for v in scores.values())}


def load_run(folder):
    events = [json.loads(line) for line in (folder / "events.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    augmentation = read_json(folder / "augmentation.json") if (folder / "augmentation.json").exists() else None
    return read_json(folder / "evi.json"), augmentation, events
