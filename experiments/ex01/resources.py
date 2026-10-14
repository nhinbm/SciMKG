"""Evidence-backed retrieval from Wikipedia and pricing snapshots, with one append-only receipt file."""
from __future__ import annotations

from pathlib import Path
import re
import time
from urllib.parse import quote

from .core import append_jsonl, digest, read_json, read_jsonl, utcnow, write_json


class ResourceClient:
    def __init__(self, cache, journal, session=None, sleeper=time.sleep, *, frozen=False):
        import requests
        self.cache, self.journal = Path(cache), journal
        self.cache.parent.mkdir(parents=True, exist_ok=True)
        self.records = {}
        for record in read_jsonl(self.cache):
            self.records.setdefault(record["key"], []).append(record)
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "SciMKG-Ex01/1.0 (educational reproduction)"})
        self.sleeper = sleeper
        self.frozen = frozen

    def get(self, url, *, stage="A", params=None, service="web", refresh=False):
        key = digest({"url": url, "params": params})
        rows = self.records.get(key, [])
        completed = [r for r in rows if r["status"] == "completed"]
        failed = [r for r in rows if r["status"] == "failed"]
        if self.frozen and not completed:
            if not failed:
                raise RuntimeError("Source has no saved receipt; frozen mode forbids new retrieval")
            saved = max(failed, key=lambda r: r["collected_at_utc"])
            self.journal.record({"kind": "cache", "stage": stage, "operation": f"{service}_failed_receipt_replay",
                "key": key, "status": "failed", "elapsed_seconds": 0, "url": url,
                "origin_event_ids": saved["origin_event_ids"], "source_status": "failed", "frozen": True})
            return saved
        if self.frozen:
            refresh = False
        if completed and not refresh:
            saved = completed[-1]
            self.journal.record({"kind": "cache", "stage": stage, "operation": f"{service}_cache",
                "key": key, "status": "completed", "elapsed_seconds": 0,
                "origin_event_ids": saved["origin_event_ids"], "url": url})
            return saved
        origin_ids = []
        for attempt in range(1, 4):
            start, stamp, response = time.monotonic(), utcnow(), None
            try:
                response = self.session.get(url, params=params, timeout=30)
                response.raise_for_status()
                if len(response.content) > 20_000_000:
                    raise ValueError("Source exceeds the 20 MB limit")
                saved = {"url": response.url, "requested_url": url, "params": params,
                         "collected_at_utc": stamp, "sha256": digest(response.content),
                         "status": "completed", "text": response.text}
                error = None
            except Exception as exc:
                error = exc
                saved = {"url": url, "collected_at_utc": stamp, "status": "failed",
                         "error_type": type(exc).__name__, "error": str(exc)[:300]}
            event = self.journal.record({"kind": "http", "stage": stage, "operation": service,
                "url": url, "params": params, "attempt": attempt, "retry": attempt > 1,
                "started_at_utc": stamp, "ended_at_utc": utcnow(), "status": saved["status"],
                "http_status": response.status_code if response is not None else None,
                "elapsed_seconds": time.monotonic() - start, "usage": None,
                "api_paid_usd": 0, "billing_mode": "public_web", "key": key,
                "error_type": saved.get("error_type")})
            origin_ids.append(event["event_id"])
            saved["origin_event_ids"] = origin_ids[:]
            if not error:
                return self._store(key, saved)
            if response is not None and response.status_code < 500 and response.status_code != 429:
                break
            if attempt < 3:
                self.sleeper(2 ** attempt)
        # Failures are kept as evidence but never become successful cached lookups.
        return self._store(key, saved)

    def _store(self, key, saved):
        record = {**saved, "key": key}
        append_jsonl(self.cache, record)
        self.records.setdefault(key, []).append(record)
        return record

    def wikipedia(self, concept):
        from bs4 import BeautifulSoup
        url = "https://zh.wikipedia.org/wiki/" + quote(concept.replace(" ", "_"), safe="")
        receipt = self.get(url, service="wikipedia")
        if receipt["status"] != "completed":
            return {"concept": concept, "grounded": False, "status": "missing_or_failed", "receipt": receipt}
        soup = BeautifulSoup(receipt["text"], "html.parser")
        content = soup.select_one(".mw-parser-output") or soup
        paragraphs = []
        for paragraph in content.find_all("p"):
            text = re.sub(r"\[\d+\]", "", paragraph.get_text(" ", strip=True))
            if len(text) >= 30:
                paragraphs.append(text)
            if sum(map(len, paragraphs)) >= 4000:
                break
        text = "\n".join(paragraphs)[:4000]
        return {"concept": concept, "grounded": bool(text), "status": "available" if text else "empty",
                "text": text, "url": receipt["url"], "source_sha256": receipt["sha256"],
                "collected_at_utc": receipt["collected_at_utc"], "receipt": receipt}


def parse_prices(html, model="gpt-6-luna"):
    from bs4 import BeautifulSoup
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    titles = {"gpt-6.1-sol": "GPT-6.1 Sol", "gpt-5.6-terra": "GPT-5.6 Terra", "gpt-6-luna": "GPT-6 Luna"}
    if model not in titles or titles[model] not in text:
        raise ValueError("Pricing page does not match the requested model")
    match = re.search(r"Text tokens\s+Per 1M tokens\s+Input\s+\$([\d.]+)\s+Cached input\s+\$([\d.]+)(?:\s+Cache writes\s+\$([\d.]+))?\s+Output\s+\$([\d.]+)", text)
    if not match:
        raise ValueError("Cannot parse pricing units or rates; inspect the saved snapshot")
    incoming, cached, writes, outgoing = match.groups()
    if writes is None and "Cache writes are billed at 1.25x" not in text:
        raise ValueError("Pricing page does not specify cache-write rates; do not assume zero")
    return {"model": model, "currency": "USD", "unit": "per_1m_tokens", "service_tier": "standard",
            "input": float(incoming), "cached_input": float(cached), "output": float(outgoing),
            "cache_write": float(writes) if writes is not None else float(incoming) * 1.25,
            "cache_write_source": "explicit_price" if writes is not None else "documented_1.25x_input",
            "long_context_threshold": 272000, "long_context_input_multiplier": 2,
            "long_context_output_multiplier": 1.5, "source": "public_price_page"}


def snapshot_prices(root, resources, model="gpt-6-luna"):
    day = utcnow()[:10]
    folder = Path(root) / "pricing"
    path = folder / f"{day}.json"
    if path.exists():
        prices = read_json(path)
        if prices["model"] != model:
            raise ValueError("Pricing snapshot belongs to a different model")
        return prices
    url = f"https://developers.openai.com/api/docs/models/{model}"
    receipt = resources.get(url, stage="preprocessing", service="pricing", refresh=True)
    if receipt["status"] != "completed":
        raise RuntimeError("Cannot retrieve the official pricing page for the run date")
    prices = {**parse_prices(receipt["text"], model), "price_date_utc": day,
              "retrieved_at_utc": receipt["collected_at_utc"], "source_url": url,
              "source_sha256": receipt["sha256"]}
    folder.mkdir(parents=True, exist_ok=True)
    local_html = Path(root) / "cache/pricing-html" / f"{day}.html"
    local_html.parent.mkdir(parents=True, exist_ok=True)
    local_html.write_text(receipt["text"], encoding="utf-8")
    write_json(path, prices)
    return prices
