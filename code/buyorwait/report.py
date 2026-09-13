"""Writes evaluation/usage_report.md for the run that produced output.csv."""
from __future__ import annotations

from datetime import datetime, timezone

from .llm import PRICES


def write_usage_report(path, evidence, n_requests, input_csv, output_csv):
    llm = getattr(evidence, "llm", None) if evidence is not None else None
    by_model = llm.usage.by_model if llm is not None else {}
    stats = evidence.stats if evidence is not None else {}
    lines = [
        "# Token usage and cost report",
        "",
        f"- Run finished: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"- Input: `{input_csv}` ({n_requests} requests) -> `{output_csv}`",
        "- Providers: Anthropic Claude API (optional; JSON-schema structured outputs) and on-device OCR",
        "  (Apple Vision, Tesseract fallback) for images.",
        "- Model use is limited to evidence interpretation (messages -> typed facts, images -> amounts).",
        "  Forecasting, plan search, ranking, verification and explanations are deterministic code (0 tokens).",
        "",
        "## Evidence processed in this run",
        "",
        "| item | count |",
        "|---|---|",
        f"| messages interpreted by the model (fresh calls) | {stats.get('message_llm', 0)} |",
        f"| messages served from the evidence cache | {max(0, stats.get('message_cached_or_llm', 0) - stats.get('message_llm', 0))} |",
        f"| messages handled by the rule-based fallback | {stats.get('message_rules', 0)} |",
        f"| model vs rule-parser disagreements on primary intent | {stats.get('message_llm_rule_disagree', 0)} |",
        f"| images read by on-device OCR (Apple Vision / Tesseract, no tokens) | {stats.get('image_ocr', 0)} |",
        f"| images read by the model (fresh calls) | {stats.get('image_llm', 0)} |",
        f"| image amounts resolved (model or cache) | {stats.get('image_resolved', 0)} |",
        f"| image amounts unresolved | {stats.get('image_unresolved', 0)} |",
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
        lines.append(f"| Anthropic | `{model}` | {m['calls']} | {m['input']:,} | {m['output']:,} | {m['cache_read']:,} | "
                     f"{m['cache_write']:,} | {total_tokens:,} | {cost:.4f} |")
        for k in ("calls", "input", "output", "cache_read", "cache_write"):
            tot[k] += m[k]
        tot["cost"] += cost
    total_tokens = tot["input"] + tot["output"] + tot["cache_read"] + tot["cache_write"]
    ocr_backends = sorted(k.split(":", 1)[1] for k in stats if k.startswith("ocr_backend:"))
    for b in ocr_backends:
        name = {"apple-vision": "Apple Vision VNRecognizeTextRequest (on-device)", "tesseract": "Tesseract OCR (local)"}.get(b, b)
        lines.append(f"| local | {name} | {stats[f'ocr_backend:{b}']} images | 0 | 0 | 0 | 0 | 0 | 0.0000 |")
    if not by_model:
        rej = llm.usage.rejected if llm is not None else 0
        state = f"{rej} request(s) rejected before billing" if rej else "not called in this run"
        lines.append("| Anthropic | `" + (llm.model if llm is not None else "claude-opus-5") +
                     f"` ({state}) | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |")
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
        "- List prices per 1M tokens (input / output): " + ", ".join(
            f"`{k}` ${v[0]:.2f} / ${v[1]:.2f}" for k, v in PRICES.items()) + ".",
        "- Cache writes are costed at 1.25x input price and cache reads at 0.1x.",
        "- Token counts are the API-reported `usage` of every call made during this run.",
        "- Only evidence belonging to users in the input file is interpreted; results are cached per",
        "  content hash (`code/cache/evidence_cache.json`), so repeat runs cost nothing.",
    ]
    if llm is not None and llm.error:
        lines += ["", f"Note: the Claude API was unavailable during this run ({llm.error.split(':')[0]}), so every",
                  "message was interpreted by the bilingual rule parser and every image by local OCR; the model",
                  "path is optional and is used automatically when an API key with credit is configured."]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
