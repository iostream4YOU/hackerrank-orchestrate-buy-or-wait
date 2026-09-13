# Token usage and cost report

- Run finished: 2026-09-13T08:39:47+00:00
- Input: `dataset/requests.csv` (250 requests) -> `output.csv`
- Providers: an LLM for evidence extraction (Google Gemini via AI Studio and/or Anthropic Claude,
  JSON-schema structured outputs) plus on-device OCR (Apple Vision, Tesseract fallback) for images.
- Model use is limited to evidence interpretation (messages -> typed facts, images -> amounts).
  Forecasting, plan search, ranking, verification and explanations are deterministic code (0 tokens).

## Evidence processed in this run

| item | count |
|---|---|
| messages interpreted by the model (fresh calls) | 198 |
| messages served from the evidence cache (earlier model calls) | 0 |
| model readings accepted (agree with the rule-parser guard) | 142 |
| model readings used where the rule parser found nothing | 0 |
| model vs rule-parser disagreements (conservative parser reading kept) | 56 |
| messages handled by the rule parser alone (no model available) | 0 |
| images read by the model (fresh calls) | 11 |
| images served from the evidence cache (earlier model calls) | 0 |
| images read by on-device OCR (cross-check, no tokens) | 11 |
| image readings where model and OCR agree | 11 |
| image readings where model and OCR disagree (OCR kept) | 0 |
| image amounts resolved / unresolved | 11 / 0 |

## Per-model usage

| provider | model | calls | input tokens | output tokens | cache read | cache write | total tokens | est. cost (USD) |
|---|---|---|---|---|---|---|---|---|
| Google (Gemini API) | `gemini-3.1-flash-lite` | 10 | 39,996 | 27,795 | 0 | 0 | 67,791 | 0.0000 |
| local | Apple Vision VNRecognizeTextRequest (on-device) | 11 images | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| **all models** | | **10** | **39,996** | **27,795** | **0** | **0** | **67,791** | **0.0000** |

## Totals for this run

- Model calls: 10
- Input tokens: 39,996 | Output tokens (incl. thinking): 27,795
- Total tokens: 67,791
- Average tokens per request: 271.2 (over 250 requests)
- Estimated total cost: $0.0000
- Estimated cost per request: $0.00000

## Pricing and method

- Prices per 1M tokens (input / output) as billed for this project: `claude-opus-5` $5.00 / $25.00, `claude-opus-4-8` $5.00 / $25.00, `claude-sonnet-5` $2.00 / $10.00, `claude-haiku-4-5` $1.00 / $5.00, `gemini-flash-latest` $0.00 / $0.00, `gemini-3.1-flash-lite` $0.00 / $0.00.
  Gemini calls run on the Google AI Studio free tier, so they are not billed.
- Output tokens include the model's thinking tokens. Cache writes are costed at 1.25x input price,
  cache reads at 0.1x (Anthropic only).
- Token counts are the API-reported usage of every call made during this run.
- Only evidence belonging to users in the input file is interpreted; results are cached per
  content hash (`code/cache/evidence_cache.json`), so repeat runs cost nothing.

## Guard decisions (model reading overruled)

- `message_18`: model ['income_confirmed', 'income_pending'] vs guard ['income_confirmed']
- `message_20`: model ['salary_continues'] vs guard ['income_amount_change']
- `message_22`: model ['income_confirmed'] vs guard ['income_confirmed']
- `message_24`: model ['income_confirmed', 'income_pending'] vs guard ['income_confirmed']
- `message_27`: model ['salary_continues'] vs guard ['income_amount_change']
- `message_29`: model ['income_confirmed'] vs guard ['income_confirmed']
- `message_31`: model ['income_confirmed'] vs guard ['income_confirmed']
- `message_32`: model ['income_confirmed'] vs guard ['income_confirmed']
- `message_38`: model ['income_confirmed'] vs guard ['income_confirmed']
- `message_53`: model ['income_confirmed'] vs guard ['income_confirmed']
- `message_54`: model ['income_confirmed'] vs guard ['income_confirmed']
- `message_62`: model ['salary_continues'] vs guard ['income_amount_change']
- `message_63`: model ['income_resumes', 'new_recurring_expense'] vs guard ['income_resumes', 'new_recurring_expense']
- `message_66`: model ['income_resumes', 'new_recurring_expense'] vs guard ['income_resumes', 'new_recurring_expense']
- `message_74`: model ['income_confirmed'] vs guard ['income_confirmed']
- `message_80`: model ['income_confirmed'] vs guard ['income_confirmed']
- `message_81`: model ['income_confirmed'] vs guard ['income_confirmed']
- `message_85`: model ['income_confirmed'] vs guard ['income_confirmed']
- `message_86`: model ['income_confirmed'] vs guard ['income_confirmed']
- `message_90`: model ['salary_continues'] vs guard ['income_amount_change']
- `message_91`: model ['income_resumes', 'new_recurring_expense'] vs guard ['income_resumes', 'new_recurring_expense']
- `message_95`: model ['income_confirmed'] vs guard ['income_confirmed']
- `message_107`: model ['income_confirmed'] vs guard ['income_confirmed']
- `message_111`: model ['income_confirmed'] vs guard ['income_confirmed']
- `message_112`: model ['salary_continues'] vs guard ['income_amount_change']
- `message_116`: model ['income_confirmed'] vs guard ['income_confirmed']
- `message_120`: model ['income_resumes', 'new_recurring_expense'] vs guard ['income_resumes', 'new_recurring_expense']
- `message_124`: model ['income_confirmed'] vs guard ['income_confirmed']
- `message_125`: model ['income_confirmed'] vs guard ['income_confirmed']
- `message_128`: model ['income_confirmed', 'income_pending'] vs guard ['income_pending', 'salary_continues']
- `message_130`: model ['income_pending', 'one_time_income_closed'] vs guard ['income_confirmed']
- `message_136`: model ['separate_obligations'] vs guard ['separate_obligations']
- `message_137`: model ['income_confirmed'] vs guard ['income_confirmed']
- `message_141`: model ['income_pending', 'one_time_income_closed'] vs guard ['income_confirmed']
- `message_143`: model ['income_confirmed'] vs guard ['income_confirmed']
- `message_145`: model [] vs guard ['income_pending']
- `message_146`: model [] vs guard ['income_pending']
- `message_149`: model ['income_confirmed'] vs guard ['income_confirmed']
- `message_156`: model ['income_confirmed'] vs guard ['income_confirmed']
- `message_161`: model ['bill_outstanding', 'separate_obligations'] vs guard ['separate_obligations']
- `message_162`: model ['income_confirmed'] vs guard ['income_confirmed']
- `message_167`: model [] vs guard ['income_pending']
- `message_173`: model ['one_time_income_closed'] vs guard ['income_confirmed']
- `message_176`: model ['salary_continues'] vs guard ['income_amount_change']
- `message_178`: model ['income_confirmed'] vs guard ['income_confirmed']
- `message_181`: model ['income_confirmed'] vs guard ['income_confirmed']
- `message_182`: model ['income_confirmed'] vs guard ['income_confirmed']
- `message_184`: model [] vs guard ['income_pending']
- `message_188`: model ['income_confirmed'] vs guard ['income_confirmed']
- `message_190`: model ['income_confirmed'] vs guard ['income_confirmed']
- `message_191`: model ['income_confirmed'] vs guard ['income_confirmed']
- `message_196`: model ['income_confirmed'] vs guard ['income_confirmed']
- `message_200`: model ['income_confirmed'] vs guard ['income_confirmed']
- `message_204`: model ['income_confirmed'] vs guard ['income_confirmed']
- `message_210`: model ['income_confirmed'] vs guard ['income_confirmed']
- `message_211`: model ['income_confirmed'] vs guard ['income_amount_change']
