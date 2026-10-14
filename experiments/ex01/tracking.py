"""W&B Models and Weave tracking; cost tables and summary come from the local journal."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import uuid

from .core import Journal, read_json, utcnow, write_json

ENTITY, PROJECT = "nhinbm-hcmus", "SciMKG"
# W&B UI Public maps to USER_READ; USER_WRITE is the separate Open mode.
PUBLIC_ACCESS = "USER_READ"


def summary_value(values, path):
    if path in values:
        return values[path]
    value = values
    for part in path.split("."):
        value = value[part]
    return value


def credentials_available():
    return session_auth() is not None


def session_auth():
    from wandb.sdk.lib.wbauth.authenticate import authenticate_session
    from wandb import Settings
    return authenticate_session(host=Settings().base_url, source="SciMKG Ex01", prompt=False)


def project_access(entity=ENTITY, project=PROJECT, *, anonymous=False):
    import requests
    from wandb import Settings
    settings = Settings()
    configured = None if anonymous else session_auth()
    if not anonymous and (configured is None or not hasattr(configured, "api_key")):
        raise RuntimeError("Local W&B API-key login is required to check project access")
    auth = None if anonymous else ("api", configured.api_key)
    query = "query Ex01Project($name:String!,$entity:String!){project(name:$name,entityName:$entity){name access}}"
    with requests.Session() as session:
        if anonymous:
            # requests otherwise silently authenticates from ~/.netrc even with auth=None.
            session.trust_env = False
        response = session.post(settings.base_url.rstrip("/") + "/graphql",
            json={"query": query, "variables": {"name": project, "entity": entity}}, auth=auth, timeout=30)
    response.raise_for_status()
    data = response.json()
    if data.get("errors"):
        raise RuntimeError("Cannot read W&B project access: " + str(data["errors"][0].get("message", "unknown"))[:200])
    result = data.get("data", {}).get("project")
    if result is None:
        raise RuntimeError("W&B project was not found or the account lacks access")
    return result["access"]


def preflight(entity=ENTITY, project=PROJECT):
    if not credentials_available():
        raise RuntimeError("W&B is not logged in. Run .venv-ex01/bin/wandb login locally; never paste credentials into chat.")
    import wandb
    api = wandb.Api(timeout=30)
    identifier = api.project(project, entity=entity).id
    access = project_access(entity, project)
    return {"authenticated": bool(identifier), "entity": entity, "project": project,
            "visibility": access, "public_verified": project_access(entity, project, anonymous=True) == PUBLIC_ACCESS
            if access == PUBLIC_ACCESS else False}


def summary_keys(report):
    """About fifteen named keys; the W&B summary panel shows these, not every nested field."""
    cost = report["cost"]
    return {"headline/llm_completed": cost["llm_completed"],
            "headline/input_tokens_cli": cost["input_tokens_cli"],
            "headline/output_tokens_cli": cost["output_tokens_cli"],
            "headline/stage_wall_seconds": cost["stage_wall_seconds"],
            "headline/evi_concepts": report.get("evi_concepts"),
            "headline/added_concepts": report.get("added_concepts"),
            "headline/explanations": report.get("explanations"),
            "headline/audio_files": report.get("audio_files"),
            "headline/rdf_triples": report.get("rdf_triples"),
            "diagnostic/llm_retries": cost["llm_retries"],
            "diagnostic/llm_failed": cost["llm_failed"],
            "diagnostic/usage_missing": cost["usage_missing"],
            "diagnostic/cache_hits": cost["cache_hits"],
            "diagnostic/cached_input_tokens_cli": cost["cached_input_tokens_cli"],
            "config/model": report["model"],
            "config/lesson_id": report["lesson_id"]}


class Tracking:
    def __init__(self, root, config, *, entity=ENTITY, project=PROJECT, mode="online"):
        self.root, self.mode = Path(root), mode
        self.entity, self.project = entity, project
        self.model, self.lesson_id = config["model"], config["lesson_id"]
        self.root.mkdir(parents=True, exist_ok=True)
        self.receipt_path = self.root / "tracking.json"
        self.receipt = read_json(self.receipt_path) if self.receipt_path.exists() else {
            "run_id": uuid.uuid4().hex[:12], "mode": mode, "entity": entity, "project": project,
            "acknowledged_event_ids": [], "trace_ids": {},
            "progress": {"calls": 0, "input_tokens_cli": 0, "output_tokens_cli": 0}, "public_verified": False}
        if any(self.receipt[k] != v for k, v in (("entity", entity), ("project", project))):
            raise ValueError("The W&B destination cannot change when resuming a run")
        self.run, self.weave_client, self.calls = None, None, {}
        if mode == "disabled":
            self.save()
            return
        import wandb
        if mode == "online":
            self.receipt["preflight"] = preflight(entity, project)
        settings = wandb.Settings(init_timeout=45)
        self.run = wandb.init(entity=entity, project=project, mode=mode,
            id=self.receipt["run_id"], resume="allow" if mode == "online" else None,
            name=f"{self.model}-{self.lesson_id}", group=self.model, job_type="inference_cost",
            tags=["Ex01", "subscription", self.model, self.lesson_id, "quality-not-measured"],
            config=config, dir=str(self.root.resolve()), settings=settings)
        self.receipt.update(mode=mode, run_url=self.run.url if mode == "online" else None,
                            wandb_directory=self.run.dir)
        if mode == "online":
            import weave
            # WAL persists SDK uploads as well as our own measured-event journal.
            self.weave_client = weave.init(f"{entity}/{project}", settings={
                "enable_wal": True, "enable_disk_fallback": True, "print_call_link": False,
                "http_timeout": 30, "retry_max_attempts": 3},
                attributes={"experiment": "Ex01", "model": self.model})
            def measured_operation(inputs):
                """Op declaration; measured timestamps/outputs are supplied from the durable journal."""
                return inputs
            self.operation = weave.op(name="scimkg_ex01_operation", enable_code_capture=False)(measured_operation)
        self.save()

    def save(self):
        write_json(self.receipt_path, self.receipt)

    def emit(self, event):
        if self.mode == "disabled":
            return
        event_id = event["event_id"]
        if event_id in self.receipt["acknowledged_event_ids"]:
            return
        if self.weave_client:
            parent = self.calls.get(event.get("parent_event_id"))
            parent_id = event.get("parent_event_id")
            if parent is None and parent_id in self.receipt["trace_ids"]:
                # Parent spans may already be acknowledged after a process restart.
                parent = self.weave_client.get_call(self.receipt["trace_ids"][parent_id])
                self.calls[parent_id] = parent
            call = self.calls.get(event_id)
            if call is None:
                call = self.weave_client.create_call(self.operation,
                    inputs=event.get("inputs") or {k: event[k] for k in ("task", "url", "operation") if k in event},
                    parent=parent, use_stack=False,
                    _call_id_override=self.receipt["trace_ids"].get(event_id, event_id),
                    attributes={"wandb_run_id": self.receipt["run_id"], "event_id": event_id,
                        "stage": event["stage"], "kind": event["kind"],
                        "billing_mode": event.get("billing_mode", "local"), "attempt": event.get("attempt"),
                        "origin_event_ids": event.get("origin_event_ids", [])},
                    display_name=f"{event['stage']} / {event.get('operation', event['kind'])}",
                    started_at=datetime.fromisoformat(event.get("started_at_utc", event["created_at_utc"])))
                self.calls[event_id] = call
                self.receipt["trace_ids"][event_id] = call.id
                if event["kind"] == "span_start" and event["stage"] == "pipeline":
                    self.receipt["root_trace_url"] = f"https://forge.coreweave.com/wandb/{self.entity}/{self.project}/r/call/{call.id}"
            if event["kind"] != "span_start":
                call.summary.update({"measured_usage": event.get("usage"), "status": event["status"],
                    "api_paid_usd": event.get("api_paid_usd"), "elapsed_seconds": event.get("elapsed_seconds"),
                    "model_requested": event.get("model_requested"), "model_actual": event.get("model_actual"),
                    "error": event.get("error"), "cache_key": event.get("key")})
                self.weave_client.finish_call(call, output=event.get("output", {"status": event["status"]}),
                    exception=RuntimeError(event["error"]) if event.get("error") else None,
                    ended_at=datetime.fromisoformat(event.get("ended_at_utc", event["created_at_utc"])))
        if event["kind"] == "llm" and event["status"] == "completed":
            usage, progress = event.get("usage") or {}, self.receipt["progress"]
            progress["calls"] += 1
            progress["input_tokens_cli"] += usage.get("input_tokens") or 0
            progress["output_tokens_cli"] += usage.get("output_tokens") or 0
            # Two cumulative series over completed calls; per-event series would drown the charts.
            self.run.log({"progress/calls": progress["calls"],
                          "progress/input_tokens_cli": progress["input_tokens_cli"],
                          "progress/output_tokens_cli": progress["output_tokens_cli"]})
        if event["kind"] != "span_start":
            # Stored event IDs and run ID make report-only retries independent of inference.
            self.receipt["acknowledged_event_ids"].append(event_id)
        self.save()

    def publish_results(self, report, root):
        if self.mode == "disabled":
            return
        import wandb
        root = Path(root)
        rows = read_json(root / "cost.json")["stages"]
        columns = list(rows[0])
        self.run.log({"cost/by_stage": wandb.Table(columns=columns, data=[[r[c] for c in columns] for r in rows])})
        for key, value in summary_keys(report).items():
            self.run.summary[key] = value
        self.run.summary["weave_root_trace_url"] = self.receipt.get("root_trace_url")
        artifact = wandb.Artifact(f"ex01-{self.receipt['run_id']}", type="experiment_results",
                                  metadata={"model": self.model, "lesson_id": self.lesson_id})
        # Explicit allowlist: never recursively upload caches, auth, or a virtual environment.
        for name in ("config.json", "summary.json", "cost.csv", "cost.md", "cost.json", "events.jsonl",
                     "batches.jsonl", "lesson.json", "evi.json", "augmentation.json", "images.json",
                     "explanations.json", "audio.json", "video.json", "triples.json", "graph.ttl"):
            if (root / name).is_file():
                artifact.add_file(str(root / name), name=name)
        for directory in ("audio", "pricing", "source_snapshot"):
            if (root / directory).is_dir():
                artifact.add_dir(str(root / directory), name=directory)
        self.run.log_artifact(artifact)
        self.save()

    def finish(self, failed=False):
        if self.weave_client:
            self.weave_client.flush()
        if self.run:
            self.run.finish(exit_code=1 if failed else 0)
        self.receipt["last_finish_at_utc"] = utcnow()
        self.save()


def publish_project_public(entity=ENTITY, project=PROJECT):
    """Publish the selected project after the Ex01 results have been prepared."""
    import requests
    import wandb
    from wandb.apis._generated import UpsertModelInput, CREATE_PROJECT_GQL
    configured = session_auth()
    if configured is None or not hasattr(configured, "api_key"):
        raise RuntimeError("No local W&B API-key login is available")
    project_id = wandb.Api(timeout=30).project(project, entity=entity).id
    payload = UpsertModelInput(id=project_id, name=project, entity_name=entity, access=PUBLIC_ACCESS)
    response = requests.post(wandb.Settings().base_url.rstrip("/") + "/graphql",
        auth=("api", configured.api_key), json={"query": CREATE_PROJECT_GQL, "variables": {"input": payload.model_dump(exclude_none=True)}}, timeout=30)
    response.raise_for_status()
    if response.json().get("errors"):
        raise RuntimeError("Cannot set public project access: " + str(response.json()["errors"][0].get("message", "unknown"))[:200])
    return preflight(entity, project)


def sync_results(root, entity, project):
    """Upload saved events and results without rerunning inference."""
    from .report import report_run
    root = Path(root)
    report = report_run(root)
    config = read_json(root / "config.json")
    tracking = Tracking(root, config, entity=entity, project=project, mode="online")
    try:
        for event in Journal(root).events():
            tracking.emit(event)
        tracking.publish_results(report, root)
    finally:
        tracking.finish()
    return report


def verify_public_results(root, entity, project):
    """Verify the project, run table, and trace using unauthenticated connections."""
    import json
    import requests
    from wandb import Settings
    root = Path(root)
    receipt = read_json(root / "tracking.json")
    query = """query Ex01PublicRun($name:String!,$entity:String!,$run:String!){
      project(name:$name,entityName:$entity){name access run(name:$run){name state summaryMetrics}}
    }"""
    with requests.Session() as session:
        session.trust_env = False
        response = session.post(Settings().base_url.rstrip("/") + "/graphql", timeout=30,
            json={"query": query, "variables": {"name": project, "entity": entity, "run": receipt["run_id"]}})
        response.raise_for_status()
        data = response.json()
        if data.get("errors") or not data.get("data", {}).get("project"):
            raise RuntimeError("Anonymous access to the W&B run could not be verified")
        remote = data["data"]["project"]
        if remote["access"] != PUBLIC_ACCESS or remote.get("run") is None:
            raise RuntimeError("The project or run is not public")
        summary = json.loads(remote["run"]["summaryMetrics"])
        local = read_json(root / "cost.json")
        if summary_value(summary, "headline/llm_completed") != local["totals"]["llm_completed"]:
            raise RuntimeError("Public W&B totals do not match the local journal")
        table = summary["cost/by_stage"]
        table_url = Settings().base_url.rstrip("/") + f"/files/{entity}/{project}/{receipt['run_id']}/" + table["path"]
        table_response = session.get(table_url, timeout=30)
        table_response.raise_for_status()
        table_data = table_response.json()
        if table_data["data"] != [[row[c] for c in table_data["columns"]] for row in local["stages"]]:
            raise RuntimeError("Public W&B table does not match the local report")
        trace_id = receipt["root_trace_url"].rsplit("/", 1)[-1]
        trace_response = session.post("https://trace.wandb.ai/call/read", timeout=30,
            json={"project_id": f"{entity}/{project}", "id": trace_id})
        trace_response.raise_for_status()
        trace = trace_response.json().get("call")
        if not trace or trace["id"] != trace_id or trace.get("ended_at") is None:
            raise RuntimeError("Weave trace is not publicly readable or has not ended")
    result = {"verified_at_utc": utcnow(), "entity": entity, "project": project,
              "visibility": "PUBLIC", "public_verified": True, "authentication": "none",
              "api_access": PUBLIC_ACCESS, "netrc_disabled": True, "run_id": receipt["run_id"],
              "state": remote["run"]["state"], "anonymous_run_read": True,
              "anonymous_cost_table_matches": True, "anonymous_weave_trace_read": True, "trace_id": trace_id}
    write_json(root / "public-verification.json", result)
    receipt.update(public_verified=True, public_verified_at_utc=result["verified_at_utc"])
    write_json(root / "tracking.json", receipt)
    return result
