"""Ex01 analysis: API-like cost, sub-step breakdown, unit costs and price conversions, from saved files only.

Reads the run folder (journal, outputs, pricing snapshot) and prices.json. It makes no model or network calls.
Writes derived tables to runs/analysis/ex01/<model>/; they can be deleted and rebuilt at any time.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RUN = ROOT / "runs/pipeline/gpt-6-luna/nervous-system"
DEFAULT_PRICES = Path(__file__).resolve().parent / "prices.json"
# Proxy tokenizer: the vendors do not publish one for these models, so every count is an estimate.
TOKENIZER = "o200k_base"
# OpenAI's documented high-detail image rule (GPT-4o family). The CLI does not report the detail level used.
IMAGE_BASE, IMAGE_TILE, TILE_PX = 85, 170, 512
# The author's configuration: E, A and explanations use DeepSeek-V3; each V pass uses the three models in
# the default --models list; image alignment uses GPT-4o.
AUTHOR_MODELS = {"E": "deepseek-v3", "A": "deepseek-v3", "explanation": "deepseek-v3", "image_alignment": "gpt-4o"}
V_PASS_MODELS = ("gpt-4o", "deepseek-v3", "gemini-1.5-flash")
STAGE_ORDER = ("E", "V", "I", "A", "image_alignment", "explanation", "audio", "export")
COST_STAGES = ("E", "V", "A", "image_alignment", "explanation")


def read_events(run):
    records = {}
    for line in (run / "events.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            event = json.loads(line)
            records[event["event_id"]] = event
    return list(records.values())


def sub_step(call):
    stage, task = call["stage"], call.get("task") or ""
    if stage == "V":
        return "V feedback" if task.endswith("/feedback") else "V refinement"
    if stage == "image_alignment":
        return f"image call {int(call.get('round') or 0) + 1}"
    return {"E": "E extraction", "A": "A concept filter", "explanation": "explanation step"}[stage]


def image_tokens(path):
    """OpenAI's high-detail rule: fit 2048px, cap the short side at 768px, then 85 + 170 per 512px tile."""
    width, height = Image.open(path).size
    scale = min(1.0, 2048 / max(width, height))
    width, height = int(width * scale), int(height * scale)
    short = min(width, height)
    if short > 768:
        factor = 768 / short
        width, height = int(width * factor), int(height * factor)
    return IMAGE_BASE + IMAGE_TILE * math.ceil(width / TILE_PX) * math.ceil(height / TILE_PX)


def usd(tokens, rate):
    return None if rate is None else tokens * rate / 1_000_000


def aggregate(items, key):
    table = {}
    for item in items:
        row = table.setdefault(key(item), {"calls": 0, "api_input": 0, "api_output": 0, "api_cost_usd": 0.0,
                                           "cli_input": 0, "cli_cached": 0, "cli_output": 0, "cli_cost_usd": 0.0,
                                           "inference_seconds": 0.0})
        row["calls"] += 1
        row["api_input"] += item["api_input"]
        row["api_output"] += item["api_output"]
        row["api_cost_usd"] += item["api_cost_usd"]
        row["cli_input"] += item["cli_input"]
        row["cli_cached"] += item["cli_cached"]
        row["cli_output"] += item["cli_output"]
        row["cli_cost_usd"] += item["cli_cost_usd"]
        row["inference_seconds"] += item["seconds"]
    return table


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--prices", type=Path, default=DEFAULT_PRICES)
    args = parser.parse_args(argv)
    run = args.run
    config = json.loads((run / "config.json").read_text(encoding="utf-8"))
    lesson = json.loads((run / "lesson.json").read_text(encoding="utf-8"))
    prices = json.loads(args.prices.read_text(encoding="utf-8"))["models"]
    model = config["model"]
    headline_price = prices[model]
    snapshot = json.loads(next((run / "pricing").glob("*.json")).read_text(encoding="utf-8"))
    if (snapshot["input"], snapshot["cached_input"], snapshot["output"]) != (
            headline_price["input"], headline_price["cached_input"], headline_price["output"]):
        raise ValueError("prices.json disagrees with the run's pricing snapshot for the run model")
    out = args.out or ROOT / "runs/analysis/ex01" / model

    import tiktoken
    encoder = tiktoken.get_encoding(TOKENIZER)
    image_paths = {image["id"]: image["path"] for image in lesson["images"]}
    image_cost = {image_id: image_tokens(path) for image_id, path in image_paths.items()}

    calls = []
    for event in read_events(run):
        if event["kind"] != "llm" or event["status"] != "completed" or not event.get("usage"):
            continue
        usage, inputs = event["usage"], event["inputs"]
        text = len(encoder.encode(inputs["prompt"])) + len(encoder.encode(json.dumps(inputs["schema"], ensure_ascii=False)))
        image = 0
        if event["stage"] == "image_alignment":
            image = image_cost[event["task"].split("/", 1)[1]]
        api_input, api_output = text + image, usage["output_tokens"]
        cli_input, cli_cached, cli_output = usage["input_tokens"], usage.get("cached_input_tokens") or 0, usage["output_tokens"]
        calls.append({"stage": event["stage"], "sub": sub_step(event), "seconds": event["elapsed_seconds"],
                      "api_input": api_input, "api_output": api_output,
                      "api_cost_usd": usd(api_input, headline_price["input"]) + usd(api_output, headline_price["output"]),
                      "cli_input": cli_input, "cli_cached": cli_cached, "cli_output": cli_output,
                      "cli_cost_usd": usd(cli_input - cli_cached, headline_price["input"]) + usd(cli_cached, headline_price["cached_input"]) + usd(cli_output, headline_price["output"])})

    by_stage = aggregate(calls, lambda c: c["stage"])
    by_sub = aggregate(calls, lambda c: c["sub"])
    # Wall time per stage comes from the runner's own table, which also covers local steps (audio, export).
    wall = {row["stage"]: row["stage_wall_seconds"] for row in json.loads((run / "cost.json").read_text(encoding="utf-8"))["stages"]}
    cost_rows = []
    for stage in STAGE_ORDER:
        row = {"level": "stage", "name": stage, **by_stage.get(stage, {"calls": 0, "api_input": 0, "api_output": 0,
               "api_cost_usd": 0.0, "cli_input": 0, "cli_cached": 0, "cli_output": 0, "cli_cost_usd": 0.0, "inference_seconds": 0.0}),
               "stage_wall_seconds": wall.get(stage, 0.0)}
        cost_rows.append(row)
    for sub, row in sorted(by_sub.items()):
        cost_rows.append({"level": "sub_step", "name": sub, **row})
    write_csv(out / "cost_by_stage.csv", cost_rows)

    total = aggregate(calls, lambda c: "all")["all"]
    n_seg, n_img = len(lesson["segments"]), len(lesson["images"])
    e_plus_v = [by_stage.get("E", {}), by_stage.get("V", {})]
    unit_rows = [
        {"key": "segment", "unit": "segment (E plus V, per transcript segment)", "count": n_seg,
         "api_input_tokens_per_unit": round((sum(x.get("api_input", 0) for x in e_plus_v)) / n_seg, 1),
         "api_output_tokens_per_unit": round((sum(x.get("api_output", 0) for x in e_plus_v)) / n_seg, 1),
         "api_cost_usd_per_unit": round(sum(x.get("api_cost_usd", 0.0) for x in e_plus_v) / n_seg, 6)},
        {"key": "image", "unit": "image (three calls, per image)", "count": n_img,
         "api_input_tokens_per_unit": round(by_stage.get("image_alignment", {}).get("api_input", 0) / n_img, 1),
         "api_output_tokens_per_unit": round(by_stage.get("image_alignment", {}).get("api_output", 0) / n_img, 1),
         "api_cost_usd_per_unit": round(by_stage.get("image_alignment", {}).get("api_cost_usd", 0.0) / n_img, 6)},
    ]
    for stage, label, key in (("A", "A call (one per filtered seed concept)", "a_call"),
                              ("explanation", "explanation (one per concept)", "explanation")):
        row = by_stage.get(stage, {})
        count = row.get("calls", 0) or 1
        unit_rows.append({"key": key, "unit": label, "count": row.get("calls", 0),
                          "api_input_tokens_per_unit": round(row.get("api_input", 0) / count, 1),
                          "api_output_tokens_per_unit": round(row.get("api_output", 0) / count, 1),
                          "api_cost_usd_per_unit": round(row.get("api_cost_usd", 0.0) / count, 6)})
    write_csv(out / "unit_costs.csv", unit_rows)

    api_in, api_out = total["api_input"], total["api_output"]
    conversion = []
    for name, rate in prices.items():
        if rate["input"] is None:
            conversion.append({"model": name, "role": rate["role"], "usd_api_like": None, "status": rate["status"]})
            continue
        cost = usd(api_in, rate["input"]) + usd(api_out, rate["output"])
        conversion.append({"model": name, "role": rate["role"], "usd_api_like": round(cost, 6),
                           "status": rate["status"]})
    write_csv(out / "price_conversion.csv", conversion)

    scenario = []
    author_total, complete = 0.0, True
    for stage in COST_STAGES:
        row = by_stage.get(stage, {"api_input": 0, "api_output": 0})
        models = V_PASS_MODELS if stage == "V" else (AUTHOR_MODELS[stage],)
        for name in models:
            rate = prices[name]
            cost = None if rate["input"] is None else usd(row["api_input"], rate["input"]) + usd(row["api_output"], rate["output"])
            complete = complete and cost is not None
            scenario.append({"stage": stage, "model": name, "tokens_in": row["api_input"],
                             "tokens_out": row["api_output"], "usd": None if cost is None else round(cost, 6)})
            author_total += cost or 0.0
    scenario.append({"stage": "total", "model": "author configuration", "tokens_in": "", "tokens_out": "",
                     "usd": round(author_total, 6), "complete": complete})
    write_csv(out / "scenario_author_config.csv", scenario)

    headline = {"model": model, "lesson_id": config["lesson_id"], "llm_calls": total["calls"],
                "api_input_tokens": api_in, "api_output_tokens": api_out,
                "api_cost_usd": round(total["api_cost_usd"], 6), "cli_cost_usd": round(total["cli_cost_usd"], 6),
                "cli_input_tokens": total["cli_input"], "cli_cached_tokens": total["cli_cached"],
                "inference_seconds": round(total["inference_seconds"], 1),
                "dominant_stage_api": max(by_stage, key=lambda s: by_stage[s]["api_cost_usd"]),
                "dominant_stage_cli": max(by_stage, key=lambda s: by_stage[s]["cli_cost_usd"]),
                "image_tokens_estimated": sum(image_cost[i] for i in image_paths),
                "tokenizer": TOKENIZER, "cache_assumption": "no cache hits in the API-like figure"}
    out.mkdir(parents=True, exist_ok=True)
    (out / "headline.json").write_text(json.dumps(headline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [f"# Ex01 analysis: {lesson['id']} ({model})", "",
             f"Lời gọi thành công: {headline['llm_calls']}. Token vào (kiểu API, ước lượng bằng {TOKENIZER}): {api_in}. "
             f"Token ra: {api_out}.", "",
             f"Tiền kiểu API (giá {model}, không cache): {headline['api_cost_usd']:.4f} USD.",
             f"Số CLI đo được (tham chiếu phụ): {headline['cli_cost_usd']:.4f} USD với {headline['cli_input_tokens']} token vào.", "",
             f"Token ảnh ước lượng theo quy tắc high detail: {headline['image_tokens_estimated']}. Mức chi tiết thật của CLI chưa biết.", "",
             "Giả định: không có cache trong số kiểu API; mọi mô hình quy đổi nhận cùng số token.",
             "Gemini 1.5 Flash chưa có giá đã xác minh, nên tổng cấu hình tác giả " + ("đầy đủ." if complete else "chưa đầy đủ."), ""]
    (out / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(headline, ensure_ascii=False, indent=2))
    return headline


if __name__ == "__main__":
    main()
