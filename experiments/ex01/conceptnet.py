"""Answer the author's ConceptNet API requests from the published 5.7.0 assertion dump.

api.conceptnet.io returns 502 for every request, so ConceptNet.py cannot reach it.
The dump holds the same edges, including the original surfaceText sentences.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import re
import sqlite3
import time
import urllib.request
from urllib.parse import parse_qs, unquote, urlsplit

import requests

from .core import ROOT, utcnow

DUMP_URL = "https://s3.amazonaws.com/conceptnet/downloads/2019/edges/conceptnet-assertions-5.7.0.csv.gz"
DUMP_SIZE = 497963447
DUMP_SHA256 = "accd65fe94038584295574ddc26e1500c1919c8c4532bf771811cafd0948af7e"
FOLDER = ROOT / "runs/preprocessing/conceptnet"
DUMP = FOLDER / "conceptnet-assertions-5.7.0.csv.gz"
INDEX = FOLDER / "conceptnet-5.7.0-zh-en.sqlite"
INDEX_VERSION = 2
# ConceptNet.py reads only node languages, terms and surfaceText; contributor lists are dropped.
KEPT_FIELDS = ("surfaceText", "weight", "dataset", "license")
# The public API answers a node query with 20 edges unless a limit is given.
API_DEFAULT_LIMIT = 20
LANGUAGES = ("zh", "en")


def term(uri):
    """Reduce a concept URI such as /c/en/neuron/n/wn/body to its term /c/en/neuron."""
    parts = uri.split("/")
    return "/".join(parts[:4]) if uri.startswith("/c/") and len(parts) >= 4 else None


def file_sha256(path):
    value = hashlib.sha256()
    with open(path, "rb") as stream:
        while chunk := stream.read(1 << 20):
            value.update(chunk)
    return value.hexdigest()


def download(target=DUMP):
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    offset = partial.stat().st_size if partial.exists() else 0
    request = urllib.request.Request(DUMP_URL, headers={"Range": f"bytes={offset}-"} if offset else {})
    with urllib.request.urlopen(request, timeout=60) as response, partial.open("ab" if offset else "wb") as stream:
        while chunk := response.read(1 << 20):
            stream.write(chunk)
    if partial.stat().st_size != DUMP_SIZE:
        raise ValueError("ConceptNet dump download is incomplete")
    partial.replace(target)


def build_index(dump=DUMP, index=INDEX):
    """Keep every edge touching a Chinese or English term, with its original JSON metadata."""
    temporary = index.with_name(index.name + ".tmp")
    temporary.unlink(missing_ok=True)
    database = sqlite3.connect(temporary)
    database.executescript("""
        PRAGMA journal_mode = OFF;
        PRAGMA synchronous = OFF;
        CREATE TABLE edges (id INTEGER PRIMARY KEY, uri TEXT, rel TEXT, start TEXT, end TEXT, info TEXT);
        CREATE TABLE nodes (term TEXT, edge INTEGER, weight REAL);
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
    """)
    edges, nodes = [], []
    with gzip.open(dump, "rt", encoding="utf-8") as stream:
        for identifier, line in enumerate(stream):
            uri, rel, start, end, info = line.rstrip("\n").split("\t")
            terms = {t for t in (term(start), term(end)) if t and t.split("/")[2] in LANGUAGES}
            if not terms:
                continue
            metadata = json.loads(info)
            kept = {k: metadata[k] for k in KEPT_FIELDS if metadata.get(k) is not None}
            weight = kept.get("weight", 1.0)
            edges.append((identifier, uri, rel, start, end, json.dumps(kept, ensure_ascii=False)))
            nodes += [(t, identifier, weight) for t in terms]
            if len(edges) >= 200_000:
                database.executemany("INSERT INTO edges VALUES (?, ?, ?, ?, ?, ?)", edges)
                database.executemany("INSERT INTO nodes VALUES (?, ?, ?)", nodes)
                edges, nodes = [], []
    database.executemany("INSERT INTO edges VALUES (?, ?, ?, ?, ?, ?)", edges)
    database.executemany("INSERT INTO nodes VALUES (?, ?, ?)", nodes)
    database.execute("CREATE INDEX node_order ON nodes (term, weight DESC, edge)")
    database.executemany("INSERT INTO meta VALUES (?, ?)", [("dump_url", DUMP_URL),
        ("dump_sha256", file_sha256(dump)), ("index_version", str(INDEX_VERSION)),
        ("languages", ",".join(LANGUAGES)), ("fields", ",".join(KEPT_FIELDS)), ("built_at_utc", utcnow())])
    database.commit()
    database.close()
    temporary.replace(index)


def ensure_index(journal, dump=DUMP, index=INDEX):
    """Download and index the dump once; later runs reuse the index."""
    if index.exists():
        return index
    with journal.span("preprocessing", "conceptnet_dump_index"):
        if not dump.exists():
            download(dump)
        if dump.stat().st_size != DUMP_SIZE or file_sha256(dump) != DUMP_SHA256:
            raise ValueError("ConceptNet dump differs from the published 5.7.0 file")
        build_index(dump, index)
    return index


def node_json(uri):
    parts = uri.split("/")
    if not uri.startswith("/c/"):
        return {"@id": uri, "label": uri}
    return {"@id": uri, "label": parts[3].replace("_", " "), "language": parts[2], "term": term(uri)}


class LocalResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


class LocalConceptNet:
    """Stand-in for the requests module inside ConceptNet.py, answering API URLs from the index."""
    exceptions = requests.exceptions

    def __init__(self, index, journal):
        self.database = sqlite3.connect(f"file:{index}?mode=ro", uri=True)
        self.meta = dict(self.database.execute("SELECT key, value FROM meta"))
        self.journal = journal
        self.seed = None
        self.english_terms = set()

    def get(self, url, params=None, timeout=None):
        start = time.monotonic()
        parts = urlsplit(url)
        node = unquote(parts.path).rstrip("/")
        query = {**{k: v[-1] for k, v in parse_qs(parts.query).items()}, **(params or {})}
        limit = int(query.get("limit", API_DEFAULT_LIMIT))
        if node.startswith("/c/zh/"):
            self.seed, self.english_terms = node.split("/")[3], set()
        elif node.startswith("/c/en/"):
            self.english_terms.add(node.split("/")[3].replace("_", " ").lower())
        rows = self.database.execute("""
            SELECT e.uri, e.rel, e.start, e.end, e.info FROM nodes n JOIN edges e ON e.id = n.edge
            WHERE n.term = ? ORDER BY n.weight DESC, n.edge LIMIT ?""", (term(node) or node, limit)).fetchall()
        edges = [{"@id": uri, "rel": {"@id": rel, "label": rel.rsplit("/", 1)[-1]},
                  "start": node_json(start), "end": node_json(end), **json.loads(info)}
                 for uri, rel, start, end, info in rows]
        self.journal.record({"kind": "local", "stage": "A", "operation": "conceptnet_dump_lookup",
            "status": "completed", "url": url, "node": node, "limit": limit, "edge_count": len(edges),
            "source": "conceptnet-assertions-5.7.0", "source_sha256": self.meta["dump_sha256"],
            "elapsed_seconds": time.monotonic() - start, "api_paid_usd": 0, "usage": None})
        return LocalResponse({"@id": node, "edges": edges})

    def close(self):
        self.database.close()


# English surfaceText templates found in the 5.7.0 dump, most specific first.
# Each has two slots; the slot that is not the seed's English term is the related concept.
# DerivedFrom has no surfaceText; Synonym texts name the same concept, so neither is used.
# Bare "X is Y" is skipped because other relations ("X is used for Y") share that form.
TEMPLATES = (
    ("IsA", r"(.+?) is a (?:type|kind) of (.+)"),
    ("PartOf", r"(.+?) is (?:a )?part of (.+)"),
    ("RelatedTo", r"(.+?) is related to (.+)"),
    ("HasContext", r"(.+?) is used in the (?:context|region) of (.+)"),
    ("DefinedAs", r"(.+?) can be defined as (.+)"),
    ("DefinedAs", r"(.+?) is the (?!opposite of )(.+)"),
    ("HasPrerequisite", r"(.+?) requires (.+)"),
)


def surface_rules(lookup):
    """Fill the empty `patterns` hole in ConceptNet.extract_cell_nouns.

    The author's function receives only the last English term, which depends on set order.
    The rule therefore anchors on every English term looked up for the current seed.
    """
    compiled = [re.compile(pattern, re.IGNORECASE) for _relation, pattern in TEMPLATES]

    def extract_cell_nouns(lines, results_term):
        anchors = lookup.english_terms | {results_term.lower()}
        nouns = set()
        for line in lines:
            text = re.sub(r"^\d+\.\s*", "", line.strip()).rstrip(".")
            for pattern in compiled:
                match = pattern.fullmatch(text)
                if not match:
                    continue
                left, right = (re.sub(r"^(a|an|the)\s+", "", g.strip(), flags=re.IGNORECASE) for g in match.groups())
                if left.lower() in anchors and right.lower() not in anchors:
                    nouns.add(right)
                elif right.lower() in anchors and left.lower() not in anchors:
                    nouns.add(left)
                break
        return sorted(nouns)

    return extract_cell_nouns
