"""Writes evaluation/usage_report.md for the run that produced output.csv."""
from __future__ import annotations

from datetime import datetime, timezone

from .llm import PRICES


def _provider(model: str) -> str:
    return "Google (Gemini API)" if model.startswith("gemini") else "Anthropic"


def write_usage_report(path, evidence, n_requests, input_csv, output_csv):
    llm = getattr(evidence, "llm", None) if evidence is not None else None
    by_model = llm.usage.by_model if llm is not None else {}
    stats = evidence.stats if evidence is not None else {}
    disagreements = getattr(evidence, "disagreements", []) if evidence is not None else []
    lines = [
        "# Token usage and cost report",
        "",
        f"- Run finished: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"- Input: `{input_csv}` ({n_requests} requests) -> `{output_csv}`",
        "- Providers: an LLM for evidence extraction (Google Gemini via AI Studio and/or Anthropic Claude,",
        "  JSON-schema structured outputs) plus on-device OCR (Apple Vision, Tesseract fallback) for images.",
        "- Model use is limited to evidence interpretation (messages -> typed facts, images -> amounts).",
        "  Forecasting, plan search, ranking, verification and explanations are deterministic code (0 tokens).",
        "",
        "## Evidence processed in this run",
        "",
        "| item | count |",
        "|---|---|",
        f"| messages interpreted by the model (fresh calls) | {stats.get('message_llm', 0)} |",
        f"| messages served from the evidence cache (earlier model calls) | {stats.get('message_model_cached', 0)} |",
        f"| model readings accepted (agree with the rule-parser guard) | {stats.get('message_model_accepted', 0)} |",
        f"| model readings used where the rule parser found nothing | {stats.get('message_model_only', 0)} |",
        f"| model vs rule-parser disagreements (conservative parser reading kept) | {stats.get('message_llm_rule_disagree', 0)} |",
        f"| messages handled by the rule parser alone (no model available) | {stats.get('message_rules', 0)} |",
        f"| images read by the model (fresh calls) | {stats.get('image_llm', 0)} |",
        f"| images served from the evidence cache (earlier model calls) | {stats.get('image_model_cached', 0)} |",
        f"| images read by on-device OCR (cross-check, no tokens) | {stats.get('image_ocr', 0)} |",
        f"| image readings where model and OCR agree | {stats.get('image_model_ocr_agree', 0)} |",
        f"| image readings where model and OCR disagree (OCR kept) | {stats.get('image_model_ocr_disagree', 0)} |",
        f"| image amounts resolved / unresolved | {stats.get('image_resolved', 0)} / {stats.get('image_unresolved', 0)} |",
        "",
        "## Per-model usage",
        "",
        "| provider | model | calls | input tokens | output tokens | cache read | cache write | total tokens | est. cost (USD) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    tot = {"calls": 0, "input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "cost": 0.0}
    for model, m in sorted(by_model.items()):
        cost = llm.usage.cost(model, m)
        total_tokens = m["input"] + m["output"] + m["cache_read"] + m["cache_write"]
        lines.append(f"| {_provider(model)} | `{model}` | {m['calls']} | {m['input']:,} | {m['output']:,} | "
                     f"{m['cache_read']:,} | {m['cache_write']:,} | {total_tokens:,} | {cost:.4f} |")
        for k in ("calls", "input", "output", "cache_read", "cache_write"):
            tot[k] += m[k]
        tot["cost"] += cost
    total_tokens = tot["input"] + tot["output"] + tot["cache_read"] + tot["cache_write"]
    ocr_backends = sorted(k.split(":", 1)[1] for k in stats if k.startswith("ocr_backend:"))
    for b in ocr_backends:
        name = {"apple-vision": "Apple Vision VNRecognizeTextRequest (on-device)", "tesseract": "Tesseract OCR (local)"}.get(b, b)
        lines.append(f"| local | {name} | {stats[f'ocr_backend:{b}']} images | 0 | 0 | 0 | 0 | 0 | 0.0000 |")
    if llm is not None and llm.usage.rejected:
        lines.append(f"| (rejected) | {llm.usage.rejected} request(s) refused before billing: {llm.error or ''} "
                     f"| 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |")
    if not by_model and (llm is None or not llm.usage.rejected):
        lines.append("| - | no model called in this run | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |")
    n = max(n_requests, 1)
    lines += [
        f"| **all models** | | **{tot['calls']}** | **{tot['input']:,}** | **{tot['output']:,}** | "
        f"**{tot['cache_read']:,}** | **{tot['cache_write']:,}** | **{total_tokens:,}** | **{tot['cost']:.4f}** |",
        "",
        "## Totals for this run",
        "",
        f"- Model calls: {tot['calls']}",
        f"- Input tokens: {tot['input']:,} | Output tokens (incl. thinking): {tot['output']:,}",
        f"- Total tokens: {total_tokens:,}",
        f"- Average tokens per request: {total_tokens / n:,.1f} (over {n_requests} requests)",
        f"- Estimated total cost: ${tot['cost']:.4f}",
        f"- Estimated cost per request: ${tot['cost'] / n:.5f}",
        "",
        "## Pricing and method",
        "",
        "- Prices per 1M tokens (input / output) as billed for this project: " + ", ".join(
            f"`{k}` ${v[0]:.2f} / ${v[1]:.2f}" for k, v in PRICES.items()) + ".",
        "  Gemini calls run on the Google AI Studio free tier, so they are not billed.",
        "- Output tokens include the model's thinking tokens. Cache writes are costed at 1.25x input price,",
        "  cache reads at 0.1x (Anthropic only).",
        "- Token counts are the API-reported usage of every call made during this run.",
        "- Only evidence belonging to users in the input file is interpreted; results are cached per",
        "  content hash (`code/cache/evidence_cache.json`), so repeat runs cost nothing.",
    ]
    if disagreements:
        lines += ["", "## Guard decisions (model reading overruled)", ""]
        lines += [f"- `{a}`: model {b} vs guard {c}" for a, b, c in disagreements]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
