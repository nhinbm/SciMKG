"""Run the author's SciMKG functions with Ex01 clients in place of their network calls."""
from __future__ import annotations

import json

from .client import CONCEPTS, EXPLANATION, FEEDBACK
from .core import unique


def bullets(terms):
    # The author parses replies with re.findall(r"-\s*(\w+)").
    return "\n".join("- " + term for term in terms)


class AuthorLLM:
    """Stand-in for NER.ner(model, prompt); the Codex client selects the actual model."""
    def __init__(self, client, lesson=None):
        self.client, self.lesson = client, lesson
        self.index, self.round, self.active = 0, 0, None
        self.raw, self.votes = {}, {}
        self.conceptnet = None
        self.concepts = ()

    def __call__(self, _requested_model, prompt):
        if "Identify all nouns/noun phrases" in prompt:
            self.active = self.lesson["segments"][self.index]["id"]
            self.index += 1
            return self.segment_call("E", CONCEPTS, prompt, "extraction")
        if "Concept Filtering Protocol" in prompt:
            return self.segment_call("V", CONCEPTS, prompt, "refinement")
        if "Analyze the extracted" in prompt:
            return self.segment_call("V", FEEDBACK, prompt, "feedback")
        if "Filter these to keep ONLY K-12 pure" in prompt:
            answer = self.client.call("A", prompt, CONCEPTS, task=f"conceptnet/{self.conceptnet.seed}")
            return bullets(unique(answer["concepts"]))
        if "Generate one concise Chinese sentence" in prompt or "Wikipedia explanation provided as" in prompt:
            # The author appends the concept to the end of both explanation prompts.
            concept = max((c for c in self.concepts if prompt.endswith(c)), key=len, default=None)
            if concept is None:
                raise ValueError("Cannot identify the concept of an explanation prompt")
            return self.client.call("explanation", prompt, EXPLANATION, task=f"explanation/{concept}")["explanation"]
        raise ValueError("Cannot identify the SciMKG stage from the prompt")

    def segment_call(self, stage, schema, prompt, operation):
        answer = self.client.call(stage, f"Segment: {self.active}. Output language: Simplified Chinese.\n{prompt}\nReturn JSON matching the schema.",
            schema, task=f"{self.active}/{operation}", round_index=self.round if stage == "V" else None)
        if schema == FEEDBACK:
            return answer["feedback"]
        terms = unique(answer["concepts"])
        if stage == "E":
            self.raw[self.active] = terms
        else:
            self.votes.setdefault(self.active, []).append(terms)
            self.round += 1
        return bullets(terms)


class PromptCapture:
    """Stand-in for requests in ImageAligment.py that records the request instead of sending it.

    imageAnalysis retries forever inside a bare except, which would swallow a budget pause,
    so Ex01 sends the captured prompt itself.
    """
    def __init__(self):
        self.payload = None

    def request(self, _method, _url, headers=None, data=None, **_kwargs):
        self.payload = json.loads(data)
        return self

    def json(self):
        return {"choices": [{"message": {"content": ""}}]}


def image_prompt(image_path, subject, concepts):
    from unittest.mock import patch
    from MultimodalAlignment import ImageAligment
    capture = PromptCapture()
    with patch.object(ImageAligment, "requests", capture):
        ImageAligment.imageAnalysis(image_path, subject, list(concepts))
    return capture.payload["messages"][0]["content"][0]["text"]


def wikipedia_lookup(resources, evidence):
    """Stand-in for get_wikipedia_summary, which needs Baidu credentials and a local proxy."""
    def get_wikipedia_summary(concept, language="en"):
        result = resources.wikipedia(concept)
        evidence[concept] = {k: result.get(k) for k in ("concept", "grounded", "status", "text", "url",
                                                        "source_sha256", "collected_at_utc")}
        return {concept: result["text"] if result["grounded"] else "not found"}
    return get_wikipedia_summary
