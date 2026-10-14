"""Durable event journal, source fingerprints, and shared utilities."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import time
import uuid
import unicodedata
from functools import lru_cache

ROOT = Path(__file__).resolve().parents[2]
STAGES = ("preprocessing", "E", "V", "I", "A", "explanation", "image_alignment",
          "video_alignment", "audio", "export")


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    return hashlib.sha256(value).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_jsonl(path):
    """Records of an append-only JSONL file; a torn last line from an interrupted write is skipped."""
    path = Path(path)
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def append_jsonl(path, record):
    """Append one record; a missing newline left by an interrupted write is repaired first."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        stream.seek(0, 2)
        if stream.tell() > 0:
            stream.seek(-1, 2)
            if stream.read(1) != b"\n":
                stream.write(b"\n")
        stream.write((json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8"))
        stream.flush()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def seconds(stamp):
    parts = [int(x) for x in stamp.split(":")]
    if len(parts) not in (2, 3) or any(x < 0 for x in parts) or any(x >= 60 for x in parts[1:]):
        raise ValueError(f"Invalid timestamp: {stamp}")
    return sum(x * 60 ** i for i, x in enumerate(reversed(parts)))


def unique(values):
    return sorted({x.strip() for x in values if isinstance(x, str) and x.strip()})


@lru_cache(maxsize=1)
def _chinese_converter():
    from opencc import OpenCC
    return OpenCC("t2s.json")


def normalize_concept(value):
    """Normalize writing variants without inferring semantic equivalence."""
    return _chinese_converter().convert(unicodedata.normalize("NFKC", value).strip())


def normalized_concepts(values):
    return unique(normalize_concept(x) for x in values if isinstance(x, str))


def revision():
    result = subprocess.run(["git", "describe", "--always", "--dirty"], cwd=ROOT,
                            capture_output=True, text=True, timeout=10)
    # Author modules the pipeline executes are part of the run's code version.
    authored = ("ExtractMultimodalConcepts/NER.py", "ExtractMultimodalConcepts/ConceptNet.py",
                "ExtractMultimodalConcepts/Wikipediaapi_model.py", "ExtractMultimodalConcepts/Translate.py",
                "MultimodalAlignment/ImageAligment.py", "RDF/rdf.py")
    files = list(Path(__file__).resolve().parent.glob("*.py")) + [ROOT / "experiments/__init__.py",
        ROOT / "scripts/experiments/ex-01/run.py"] + [ROOT / name for name in authored]
    return {"git_revision": result.stdout.strip() or "unknown",
            "source_sha256": {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in sorted(files)}}


def environment():
    result = {}
    for name in ("wandb", "weave", "rdflib", "requests", "Pillow", "jsonschema", "Wikipedia-API", "openai"):
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = None
    cli = subprocess.run(["codex", "--version"], capture_output=True, text=True, timeout=10)
    result["codex_cli"] = cli.stdout.strip()
    return result


class Journal:
    """One line per completed event; the local journal is the accounting source."""
    def __init__(self, root, listener=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.listener = listener
        self.path = self.root / "events.jsonl"
        self.context = []

    def events(self):
        if not self.path.exists():
            return []
        records = {}
        for line in self.path.read_text().splitlines():
            if line.strip():
                event = json.loads(line)
                records[event["event_id"]] = event
        return list(records.values())

    def record(self, event):
        record = {"event_id": str(uuid.uuid4()),
                  "created_at_utc": utcnow(), **event}
        if self.context:
            record.setdefault("parent_event_id", self.context[-1])
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
            stream.flush()
        if self.listener:
            # Tracking errors cannot discard measured inference or trigger inference retries.
            try:
                self.listener(record)
            except Exception as exc:
                write_json(self.root / "tracking-pending.json", {"error": type(exc).__name__,
                           "recorded_at_utc": utcnow(), "pending_event_id": record["event_id"]})
        return record

    @contextmanager
    def span(self, stage, operation=None, **metadata):
        identifier = str(uuid.uuid4())
        parent = self.context[-1] if self.context else None
        start, stamp = time.monotonic(), utcnow()
        self.context.append(identifier)
        state = {"status": "completed"}
        self.record({"event_id": identifier, "parent_event_id": parent, "kind": "span_start",
                     "stage": stage, "operation": operation or stage, "started_at_utc": stamp,
                     "status": "running", **metadata})
        try:
            yield state
        except BaseException as exc:
            state.update(status=getattr(exc, "journal_status",
                         "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"),
                         error_type=type(exc).__name__, error=str(exc)[:500])
            raise
        finally:
            self.context.pop()
            self.record({"event_id": identifier, "parent_event_id": parent, "kind": "span",
                         "stage": stage, "operation": operation or stage, "started_at_utc": stamp,
                         "ended_at_utc": utcnow(), "elapsed_seconds": time.monotonic() - start,
                         **metadata, **state})

