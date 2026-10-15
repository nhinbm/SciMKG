"""Queries for Ex03: lecture sentences (verbatim) and student-style questions rewritten from them.

The answer of every query is the segment its source sentence comes from; no model or person labels it.
"""
from __future__ import annotations

from pathlib import Path
import re

from experiments.ex01.core import ROOT, Journal, normalize_concept, read_json, write_json
from experiments.ex02.lessons import lesson_ids, prepare_lesson

QUERY_ROOT = ROOT / "runs/experiments/ex-03/queries"
MIN_CHARACTERS = 15
# A rewrite whose bigrams mostly come from its source sentence is flagged, not dropped.
OVERLAP_FLAG = 0.5
QUESTION = {"type": "object", "properties": {"question": {"type": "string"}},
            "required": ["question"], "additionalProperties": False}
PROMPT = """Subject: {subject}. The sentence below comes from a Chinese middle-school lecture.
Write one question in Simplified Chinese that a student could ask whose answer is in this sentence.
The question must be specific to what this sentence says, not a general question about the lesson.
Keep the scientific terms of the sentence as they are; say everything else in your own words, and do not state the answer.
Sentence: {sentence}"""


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[。！？!?])", text) if len(s.strip()) >= MIN_CHARACTERS]


def bigrams(text):
    text = re.sub(r"[\W_]+", "", normalize_concept(text))
    return {text[i:i + 2] for i in range(len(text) - 1)}


def overlap(query, source):
    mine = bigrams(query)
    return len(mine & bigrams(source)) / len(mine) if mine else 0.0


def source_sentences():
    rows = []
    for lesson_id in lesson_ids():
        lesson = read_json(prepare_lesson(lesson_id))
        for segment in lesson["segments"]:
            for index, sentence in enumerate(sentences(segment["text"])):
                rows.append({"id": f"{lesson_id}/{segment['id']}/{index:02d}", "lesson_id": lesson_id,
                             "subject": lesson["subject"], "segment_id": segment["id"], "sentence": sentence})
    return rows


def build(client=None, root=QUERY_ROOT):
    """Write queries.json; with a client, add the rewritten questions (cached, so a rerun makes no new call)."""
    root = Path(root)
    rows = source_sentences()
    path = root / "queries.json"
    if path.exists():
        saved = read_json(path)
        if [(r["id"], r["sentence"]) for r in saved["queries"]] != [(r["id"], r["sentence"]) for r in rows]:
            raise ValueError("Source sentences changed; the frozen query set cannot be rebuilt in place")
        # Rewrites made with another prompt belong to a different query set and are not reused.
        rewritten = {r["id"]: r for r in saved["queries"] if r.get("question")} if saved["rewrite_prompt"] == PROMPT else {}
    else:
        rewritten = {}
    for row in rows:
        if row["id"] in rewritten:
            row.update({k: rewritten[row["id"]][k] for k in ("question", "overlap", "overlap_flag")})
    journal = Journal(root)
    for row in rows:
        if client is not None and "question" not in row:
            with journal.span("query_generation", "rewrite_question", query_id=row["id"]):
                answer = client.call("query_generation", PROMPT.format(subject=row["subject"], sentence=row["sentence"]),
                                     QUESTION, task=f"query/{row['id']}")
            row["question"] = answer["question"].strip()
            row["overlap"] = round(overlap(row["question"], row["sentence"]), 4)
            row["overlap_flag"] = row["overlap"] > OVERLAP_FLAG
        # Write after every row so a quota stop keeps what is done.
        write_json(path, {"min_characters": MIN_CHARACTERS, "overlap_flag_threshold": OVERLAP_FLAG,
                          "rewrite_prompt": PROMPT, "rewrite_quality_review": "not_measured", "queries": rows})
    return read_json(path)
