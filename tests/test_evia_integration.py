"""Offline regressions for EVIA voting, using the actual pipeline functions.

The upstream API caller still contains blank configuration placeholders.
Load only the functions preceding it, without importing network integrations.
"""

import ast
from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import re
import tempfile
from typing import Tuple
import unittest
from unittest.mock import Mock


def load_pipeline_functions():
    source = Path(__file__).resolve().parents[1] / "ExtractMultimodalConcepts" / "NER.py"
    tree = ast.parse(source.read_text(encoding="utf-8").split("\ndef ner(", 1)[0])
    names = {"extractConcepts", "Extraction", "Validation", "SELF_REFINE", "Intergration"}
    tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = {"os": os, "re": re, "Tuple": Tuple, "finalEntity": set()}
    exec(compile(tree, str(source), "exec"), namespace)
    return namespace


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.pipeline = load_pipeline_functions()
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.path = str(Path(self.tempdir.name) / "lesson.txt")
        self.output = io.StringIO()

    def integrate(self, votes, model_count=3, k=5, alpha=0.7, maxima=None):
        concepts = list(votes)
        candidate = [["00:00-00:10", concepts, [votes[c] + 1 for c in concepts], "",
                      maxima if maxima is not None else [0] * len(concepts)]]
        with redirect_stdout(self.output):
            result = self.pipeline["Intergration"](
                candidate, k, self.path, model_count=model_count, alpha=alpha
            )
        return result[0][1]

    def test_threshold_rejects_zero_and_ten_votes_accepts_eleven_and_all_votes(self):
        self.assertEqual(
            self.integrate({"zero": 0, "below": 10, "above": 11, "all": 15}),
            {"above", "all"},
        )
        stored = Path(self.path.replace(".txt", "_Intergrationner")).read_text(encoding="utf-8")
        self.assertEqual(set(stored.splitlines()[1].split()), {"above", "all"})
        self.assertEqual(self.pipeline["finalEntity"], {"above", "all"})

    def test_accepts_exact_threshold(self):
        self.assertEqual(self.integrate({"below": 6, "at": 7}, model_count=2), {"at"})

    def test_denominator_uses_actual_model_count(self):
        self.assertEqual(self.integrate({"below": 3, "above": 4}, model_count=1), {"above"})

    def test_one_model_unanimity_cannot_bypass_group_threshold(self):
        self.assertEqual(self.integrate({"one_model_only": 5}, maxima=[5]), set())

    def test_one_round_rejects_extraction_only_candidate(self):
        self.assertEqual(self.integrate({"unvalidated": 0, "validated": 1}, model_count=1, k=1),
                         {"validated"})

    def test_custom_threshold_is_applied(self):
        self.assertEqual(self.integrate({"half": 5, "all": 10}, model_count=2, alpha=1), {"all"})

    def test_rejects_invalid_counts_thresholds_and_scores(self):
        for settings in ({"k": 0}, {"k": -1}, {"model_count": 0}, {"model_count": -1},
                         {"alpha": -0.1}, {"alpha": 1.1}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                self.integrate({"concept": 0}, **settings)
        for votes in (-1, 16):
            with self.subTest(votes=votes), self.assertRaises(ValueError):
                self.integrate({"concept": votes})
        with self.assertRaises(ValueError):
            self.pipeline["Intergration"]([["time", ["concept"], [], "", [0]]], 5, self.path, 3)

    def test_empty_candidates_produce_empty_output(self):
        self.assertEqual(self.integrate({}), set())

    def test_small_author_sample_vote_replay(self):
        # Zenodo 19691725, RawData.zip: Biology/bx1/11第2节_细胞器之间的分工合作（第一课
        # The lesson's _Validationner SHA-256:
        # 3e063d1a3dc59f095407397734e088577817bbb908cd156ba8b44225f9754221
        # Only two paragraphs; expected output follows this fork's voting policy.
        candidate = [
            ["06:35-07:11", ["结构模式图", "有氧呼吸"], [2, 16], "", [1, 1]],
            ["07:11-08:07", ["内膜", "嵴", "酶", "能量供应"], [9, 8, 14, 14], "", [1, 1, 1, 1]],
        ]
        with redirect_stdout(self.output):
            result = self.pipeline["Intergration"](candidate, 5, self.path, model_count=3)
        self.assertEqual(result, [
            ["06:35-07:11", {"有氧呼吸"}],
            ["07:11-08:07", {"酶", "能量供应"}],
        ])

    def test_extraction_starts_per_model_count_at_zero(self):
        Path(self.path).write_text('"00:00-00:10": "生物学"\n', encoding="utf-8")
        self.pipeline["ner"] = Mock(return_value="- 细胞")
        with redirect_stdout(self.output):
            result = self.pipeline["Extraction"](self.path, ["model"], "biology", set(), 1)
        self.assertEqual(result[0][1], {"细胞"})
        self.assertEqual(result[0][2], [1])
        self.assertEqual(result[0][4], [0])

    def test_extraction_validation_integration_wiring_and_vote_counters(self):
        concepts = ["低票", "临界下", "临界上"]
        candidate = [["00:00-00:10", concepts, [1, 1, 1], "", [0, 0, 0]]]
        extraction = Mock(return_value=candidate)
        self.pipeline["Extraction"] = extraction
        rounds = {"a": 0, "b": 0, "c": 0}
        calls = []

        def fake_ner(model, prompt):
            calls.append(model)
            if "Concept Filtering Protocol" not in prompt:
                return ""
            if model == "a":
                kept = ["低票", "临界下"]
                if rounds[model] == 0:
                    kept.append("临界上")
            elif model == "b":
                kept = ["临界下", "临界上"]
            else:
                kept = ["临界上"]
            rounds[model] += 1
            return "\n".join("- " + concept for concept in kept)

        self.pipeline["ner"] = fake_ner
        with redirect_stdout(self.output):
            result = self.pipeline["extractConcepts"](self.path, ["a", "b", "c"], "biology", set(), 5)
        self.assertEqual(rounds, {"a": 5, "b": 5, "c": 5})
        self.assertEqual(calls, ["a"] * 10 + ["b"] * 10 + ["c"] * 10)
        self.assertEqual(candidate[0][2], [6, 11, 12])
        self.assertEqual(candidate[0][4], [5, 5, 5])
        self.assertEqual(result, [["00:00-00:10", {"临界上"}]])
        extraction.assert_called_once()


if __name__ == "__main__":
    unittest.main()
