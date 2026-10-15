"""Subscription Claude client: the same contract as CodexClient (cache, journal, retries, usage hook), for Claude via `claude -p`."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time

from .client import CONCEPTS, FatalInferenceError, UsageLimitError
from .core import append_jsonl, digest, read_jsonl, utcnow

# Variables that make `claude` bill an API or another provider instead of the claude.ai subscription.
API_BILLING_VARIABLES = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
                         "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX")
# Same wording as CodexClient, so the two backends receive identical task text.
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")  # values listed by `claude --help`
INSTRUCTION = ("Perform only the following inference task and return JSON matching the schema. "
               "Do not use tools, read files, or browse the web.\n")


class ClaudeCliClient:
    """Adapter with the CodexClient interface: call(stage, prompt, schema, ...) returns validated JSON."""

    def __init__(self, cache, journal, model="claude-haiku-5-5", *, effort="low", timeout=180, retries=3,
                 executor=subprocess.run, sleeper=time.sleep, require_login=True, before_launch=None):
        if effort not in EFFORT_LEVELS:
            raise ValueError(f"effort must be one of {EFFORT_LEVELS}")
        self.cache, self.journal = Path(cache), journal
        self.model, self.effort, self.timeout, self.retries = model, effort, timeout, retries
        self.executor, self.sleeper, self.before_launch = executor, sleeper, before_launch
        self.env = {k: v for k, v in os.environ.items() if k not in API_BILLING_VARIABLES}
        self.records = {record["key"]: record for record in read_jsonl(self.cache)}
        if require_login:
            self.check_login()

    def check_login(self):
        status = self.executor(["claude", "auth", "status"], capture_output=True, text=True,
                               env=self.env, timeout=20)
        info = self.parse_json(status.stdout) or {}
        if (status.returncode or not info.get("loggedIn") or info.get("authMethod") != "claude.ai"
                or info.get("apiProvider") != "firstParty"):
            raise FatalInferenceError("Claude is not logged in with a claude.ai subscription; "
                                      "paid API fallback is disabled")

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
        if image:
            raise FatalInferenceError("ClaudeCliClient takes text only; image input is not wired for Claude")
        actual_prompt = INSTRUCTION + prompt
        payload = {"client_protocol": 2, "backend": "claude_cli", "model": self.model,
                   "reasoning_effort": self.effort, "stage": stage, "prompt": actual_prompt, "schema": schema,
                   "task": task, "round": round_index, "image_sha256": None}
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
            error, usage, response, reply = None, None, None, None
            try:
                argv = ["claude", "-p", "--model", self.model, "--effort", self.effort, "--output-format", "json",
                        "--json-schema", json.dumps(schema, ensure_ascii=False), "--tools", "",
                        "--no-session-persistence"]
                try:
                    result = self.executor(argv, input=actual_prompt, capture_output=True, text=True,
                                           env=self.env, timeout=timeout)
                except subprocess.TimeoutExpired as exc:
                    raise TimeoutError("Claude request timed out") from exc
                reply = self.parse_json(result.stdout)
                usage = self.usage(reply)
                if result.returncode or reply is None or reply.get("is_error") or reply.get("subtype") != "success":
                    messages = (result.stderr or "") + " " + json.dumps(reply or result.stdout[:300], ensure_ascii=False)
                    if "usage limit" in messages.lower() or "rate limit" in messages.lower():
                        raise UsageLimitError("Claude subscription usage limit reached")
                    if any(token in messages.lower() for token in ("unauthorized", "authentication", "not found", "invalid model")):
                        raise FatalInferenceError("Authentication or model access failed; inspect the local events")
                    raise RuntimeError("Claude did not complete the request")
                response = reply.get("structured_output")
                if response is None:
                    raise RuntimeError("Claude returned no structured output")
                jsonschema.validate(response, schema)
                status = "completed"
            except KeyboardInterrupt as exc:
                error, status, response = exc, "interrupted", None
            except Exception as exc:
                error, status, response = exc, "failed", None
            record = self.journal.record({"kind": "llm", "stage": stage, "operation": "claude_cli",
                "key": key, "task": task, "round": round_index, "attempt": attempt, "retry": attempt > 1,
                "started_at_utc": stamp, "ended_at_utc": utcnow(), "elapsed_seconds": time.monotonic() - start,
                "status": status, "model_requested": self.model, "model_actual": self.model_actual(reply),
                "model_snapshot": None, "authentication": "claude.ai", "billing_mode": "subscription",
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
    def parse_json(text):
        try:
            value = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def model_actual(reply):
        # The CLI names the model it used in modelUsage; record that name rather than trusting the request.
        if not reply or not isinstance(reply.get("modelUsage"), dict) or not reply["modelUsage"]:
            return None
        return next(iter(reply["modelUsage"]))

    @staticmethod
    def usage(reply):
        if not reply or not isinstance(reply.get("usage"), dict):
            return None
        usage = reply["usage"]
        model_usage = next(iter((reply.get("modelUsage") or {}).values()), {})
        return {"input_tokens": usage.get("input_tokens"),
                "cache_write_tokens": usage.get("cache_creation_input_tokens"),
                "cache_read_tokens": usage.get("cache_read_input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "thinking_tokens": model_usage.get("thinkingTokens"),
                "source": "claude_cli_result",
                # The CLI's own estimate at API list prices. Under a subscription nothing is billed per call.
                "estimated_api_equivalent_usd": reply.get("total_cost_usd")}
