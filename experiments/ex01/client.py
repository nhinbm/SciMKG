"""Subscription Codex client: one JSONL cache, usage capture for every attempt, and a hook before each launch."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

from .core import append_jsonl, digest, read_json, read_jsonl, utcnow, write_json

CONCEPTS = {"type": "object", "properties": {"concepts": {"type": "array", "items": {"type": "string"}}},
            "required": ["concepts"], "additionalProperties": False}
FEEDBACK = {"type": "object", "properties": {"feedback": {"type": "string"}},
            "required": ["feedback"], "additionalProperties": False}
EXPLANATION = {"type": "object", "properties": {"explanation": {"type": "string"}},
               "required": ["explanation"], "additionalProperties": False}
EXPANSION = {"type": "object", "properties": {"accepted": {"type": "array", "items": {
    "type": "object", "properties": {"candidate_id": {"type": "string"}, "concept_zh": {"type": "string"}},
    "required": ["candidate_id", "concept_zh"], "additionalProperties": False}}},
    "required": ["accepted"], "additionalProperties": False}

# (name used in this code, name in the CLI usage object). The CLI reports cache writes as
# `cache_write_input_tokens`; reading any other name silently stores None.
USAGE_FIELDS = (("input_tokens", "input_tokens"), ("cached_input_tokens", "cached_input_tokens"),
                ("cache_write_tokens", "cache_write_input_tokens"), ("output_tokens", "output_tokens"),
                ("reasoning_output_tokens", "reasoning_output_tokens"))
TOOL_ITEMS = ("command_execution", "mcp_tool_call", "web_search")


def normalized_usage(events):
    turns = [e["usage"] for e in events if e.get("type") == "turn.completed" and isinstance(e.get("usage"), dict)]
    if not turns:
        return None
    result = {}
    for name, source in USAGE_FIELDS:
        values = [u.get(source) for u in turns]
        result[name] = sum(values) if all(isinstance(v, int) and v >= 0 for v in values) else None
    result["source"] = "codex_turn_completed"
    result["completed_turns"] = len(turns)
    if len(turns) > 1:
        # Long-context rates apply to each request, never to the sum of requests.
        result["turn_usage"] = turns
    return result


def reset_hint(text):
    """Keep the reset time that the CLI prints with a usage-limit rejection."""
    match = re.search(r"try again at ([^.'\"}\n]+)", text)
    return f"try again at {match.group(1).strip()}" if match else "no reset time was reported"


def _text(value):
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value or ""


class FatalInferenceError(RuntimeError):
    pass


class UsageLimitError(FatalInferenceError):
    """Stop immediately when the subscription usage limit is reached; the message keeps the reset time."""


class CodexClient:
    def __init__(self, cache, journal, model="gpt-6-luna", *, timeout=180, retries=3,
                 executor=subprocess.run, sleeper=time.sleep, require_login=True, before_launch=None):
        self.cache, self.journal = Path(cache), journal
        self.model, self.timeout, self.retries = model, timeout, retries
        self.executor, self.sleeper, self.before_launch = executor, sleeper, before_launch
        self.env = {k: v for k, v in os.environ.items() if k not in (
            "OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN", "WANDB_API_KEY")}
        self.records = {record["key"]: record for record in read_jsonl(self.cache)}
        if require_login:
            self.check_login()

    def check_login(self):
        status = self.executor(["codex", "-c", 'forced_login_method="chatgpt"', "login", "status"],
                               capture_output=True, text=True, env=self.env, timeout=20)
        if status.returncode or "Logged in using ChatGPT" not in status.stdout + status.stderr:
            raise FatalInferenceError("Codex is not logged in with ChatGPT; paid API fallback is disabled")

    def _cached(self, payload):
        import jsonschema
        key = digest(payload)
        saved = self.records.get(key)
        if saved is None:
            return None
        if saved["payload"] != payload:
            raise ValueError("Cache payload does not match its key")
        jsonschema.validate(saved["response"], payload["schema"])
        if digest(saved["response"]) != saved["response_sha256"]:
            raise ValueError("Cached response has changed")
        self.journal.record({"kind": "cache", "stage": payload["stage"], "operation": "llm_cache",
            "task": payload["task"], "key": key, "status": "completed", "elapsed_seconds": 0,
            "origin_event_ids": saved["origin_event_ids"], "origin_usage": saved["usage"], "usage": None})
        return saved["response"]

    def call(self, stage, prompt, schema=CONCEPTS, *, image=None, task=None, round_index=None):
        import jsonschema
        instruction = "Perform only the following inference task and return JSON matching the schema. Do not use tools, read files, or browse the web.\n"
        actual_prompt = instruction + prompt
        payload = {"client_protocol": 2, "model": self.model, "reasoning_effort": "low", "stage": stage,
                   "prompt": actual_prompt, "schema": schema, "task": task, "round": round_index,
                   "image_sha256": digest(Path(image).read_bytes()) if image else None}
        key = digest(payload)
        cached = self._cached(payload)
        if cached is not None:
            return cached
        origin_ids = []
        for attempt in range(1, self.retries + 1):
            # Runs before anything is recorded, so a budget pause leaves no trace of a launch.
            remaining = self.before_launch() if self.before_launch else float("inf")
            timeout = min(self.timeout, remaining)
            start, stamp = time.monotonic(), utcnow()
            error, usage, response = None, None, None
            try:
                with tempfile.TemporaryDirectory(prefix="scimkg-ex01-codex-") as temp:
                    folder = Path(temp)
                    write_json(folder / "schema.json", schema)
                    argv = ["codex", "exec", "--ignore-user-config", "--ephemeral", "--skip-git-repo-check",
                            "--sandbox", "read-only", "--json", "-m", self.model,
                            "-c", 'forced_login_method="chatgpt"', "-c", 'model_provider="openai"',
                            "-c", 'model_reasoning_effort="low"', "--output-schema", str(folder / "schema.json"),
                            "-o", str(folder / "reply.json"), "-C", temp]
                    for feature in ("shell_tool", "multi_agent", "apps", "plugins", "browser_use",
                                    "computer_use", "skill_search", "image_generation"):
                        argv += ["--disable", feature]
                    if image:
                        argv += ["--image", str(Path(image).resolve())]
                    argv += ["-"]
                    try:
                        result = self.executor(argv, input=actual_prompt, capture_output=True, text=True,
                                               env=self.env, timeout=timeout)
                    except subprocess.TimeoutExpired as exc:
                        usage = normalized_usage(self.parse_events(_text(exc.stdout)))
                        raise TimeoutError("Codex request timed out") from exc
                    events = self.parse_events(result.stdout)
                    usage = normalized_usage(events)
                    if any(e.get("item", {}).get("type") in TOOL_ITEMS for e in events):
                        raise FatalInferenceError("Codex used tools in an inference-only request")
                    if result.returncode or usage is None:
                        messages = result.stderr + " " + " ".join(str(e.get("error", e.get("message", ""))) for e in events)
                        if "usage limit" in messages.lower():
                            raise UsageLimitError(f"Codex subscription usage limit reached; {reset_hint(messages)}")
                        if any(token in messages.lower() for token in ("unauthorized", "authentication", "not supported", "not found", "invalid model", "not available")):
                            raise FatalInferenceError("Authentication or model access failed; inspect the local events")
                        raise RuntimeError("Codex did not complete the request")
                    response = read_json(folder / "reply.json")
                    jsonschema.validate(response, schema)
                    if schema == EXPLANATION and not response["explanation"].strip():
                        raise ValueError("Empty explanation")
                status = "completed"
            except KeyboardInterrupt as exc:
                error, status, response = exc, "interrupted", None
            except Exception as exc:
                error, status, response = exc, "failed", None
            record = self.journal.record({"kind": "llm", "stage": stage, "operation": "codex_exec",
                "key": key, "task": task, "round": round_index, "attempt": attempt, "retry": attempt > 1,
                "started_at_utc": stamp, "ended_at_utc": utcnow(), "elapsed_seconds": time.monotonic() - start,
                "status": status, "model_requested": self.model, "model_actual": self.model,
                "model_snapshot": None, "authentication": "chatgpt", "billing_mode": "subscription",
                "api_paid_usd": None, "usage": usage, "inputs": payload, "output": response,
                "error_type": type(error).__name__ if error else None,
                "error": str(error)[:500] if error else None,
                **({"request_inputs_available": True} if status == "interrupted" else {})})
            origin_ids.append(record["event_id"])
            if error is None:
                entry = {"key": key, "payload": payload, "response": response, "response_sha256": digest(response),
                         "usage": usage, "origin_event_ids": origin_ids}
                append_jsonl(self.cache, entry)
                self.records[key] = entry
                return response
            if isinstance(error, (FatalInferenceError, KeyboardInterrupt)) or attempt == self.retries:
                raise error
            self.sleeper(2 ** attempt)
        raise AssertionError("Unreachable")

    @staticmethod
    def parse_events(stdout):
        result = []
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
                if isinstance(event, dict):
                    result.append(event)
            except json.JSONDecodeError:
                continue
        return result
