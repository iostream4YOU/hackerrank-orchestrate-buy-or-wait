# Token usage and cost report

- Run finished: 2026-09-12T17:34:11+00:00
- Input: `dataset/requests.csv` (250 requests) -> `output.csv`
- Providers: Anthropic Claude API (optional; JSON-schema structured outputs) and on-device OCR
  (Apple Vision, Tesseract fallback) for images.
- Model use is limited to evidence interpretation (messages -> typed facts, images -> amounts).
  Forecasting, plan search, ranking, verification and explanations are deterministic code (0 tokens).

## Evidence processed in this run

| item | count |
|---|---|
| messages interpreted by the model (fresh calls) | 0 |
| messages served from the evidence cache | 0 |
| messages handled by the rule-based fallback | 198 |
| model vs rule-parser disagreements on primary intent | 0 |
| images read by on-device OCR (Apple Vision / Tesseract, no tokens) | 11 |
| images read by the model (fresh calls) | 0 |
| image amounts resolved (model or cache) | 11 |
| image amounts unresolved | 0 |

## Per-model usage

| provider | model | calls | input tokens | output tokens | cache read | cache write | total tokens | est. cost (USD) |
|---|---|---|---|---|---|---|---|---|
| local | Apple Vision VNRecognizeTextRequest (on-device) | 11 images | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| Anthropic | `claude-opus-5` (1 request(s) rejected before billing) | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| **all models** | | **0** | **0** | **0** | **0** | **0** | **0** | **0.0000** |

## Totals for this run

- Model calls: 0
- Input tokens: 0 | Output tokens (incl. thinking): 0
- Total tokens: 0
- Average tokens per request: 0.0 (over 250 requests)
- Estimated total cost: $0.0000
- Estimated cost per request: $0.00000

## Pricing and method

- List prices per 1M tokens (input / output): `claude-opus-5` $5.00 / $25.00, `claude-opus-4-8` $5.00 / $25.00, `claude-sonnet-5` $2.00 / $10.00, `claude-haiku-4-5` $1.00 / $5.00.
- Cache writes are costed at 1.25x input price and cache reads at 0.1x.
- Token counts are the API-reported `usage` of every call made during this run.
- Only evidence belonging to users in the input file is interpreted; results are cached per
  content hash (`code/cache/evidence_cache.json`), so repeat runs cost nothing.

Note: the Claude API was unavailable during this run (BadRequestError), so every
message was interpreted by the bilingual rule parser and every image by local OCR; the model
path is optional and is used automatically when an API key with credit is configured.
