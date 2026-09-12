# AI Judge interview — prep notes (Buy or Wait?)

Not part of `code.zip`. Read this once before the interview; everything here is backed by the code.

## 60-second pitch

"I built a deterministic cash-flow engine with a narrow evidence layer. The engine reconstructs each
user's recurring income and expenses from history, simulates the balance day by day, and evaluates
every allowed plan — full, the seller's installment options, partial, wait, or full payment with
permitted spending cuts — against the minimum-balance rule, then ranks them exactly as the problem
statement specifies and verifies every row before writing it. Messages and images are untrusted, so
they are only ever converted into typed facts — never into instructions — and deterministic code
decides what a fact changes. I calibrated every forecast rule against the 25 labelled samples and
checked that each tuned setting is best on both halves of the samples, so it is not memorised."

## Why this architecture

- Scoring is exact match on amounts, dates, enums. A 90-day running-balance simulation across 250
  users is arithmetic; code gets it exactly right, an LLM approximates it.
- Models are used only where language/vision is needed: messages -> typed facts, images -> amounts.
- Safety by construction: message text never reaches a decision prompt; outputs are schema-validated;
  instruction-bearing messages (the planted "pay the release charge today" scam) change nothing.
- Cost: the default run is $0 (rule parser for messages, on-device OCR for images). With a funded key,
  Claude (`claude-opus-5`, JSON-schema outputs) interprets messages and is cross-checked against the
  rule parser; results are cached by content hash.

## Key findings (be ready to explain each)

1. **Two forecasts.** `amount_safe_to_pay` and `earliest_date_for_full_payment` use the baseline with no
   spending changes and ignore payment preferences; the recommendation may add changes. Proof:
   request_06 shows astp 603.3 < 620.4 and earliest after the deadline, yet "stop streaming, pay in full
   today" — only coherent with two forecasts.
2. **Ranking** follows the problem statement. request_19 picks partial over installments because
   partial costs less in total (installments carry a fee) — a fixed decision order gets it wrong.
3. **Variable spending = ceil(mean) of history** ("forecast conservatively"). Decoding request_22 and
   request_06 by hand reproduced the reference outflow to the cent.
4. **Dead series:** income/expense streams whose next expected date has already passed have stopped
   (final payroll, ended household income). Stops user_05/user_13 from being credited income they
   no longer receive.
5. **Request-day rule:** an occurrence due on the request date is already in the balance.
6. **Horizon:** three no-income samples each lose exactly their third rent on days 87-90, so the
   reference effectively ignores the last days; 86 days fits; split-half check says it is stable.
7. **Gross vs net salary:** "confirmed base salary X" messages quote gross pay — exactly 1.67x the
   observed deposits — so they confirm the salary without changing it (fixed request_11). A raise
   message ("increased to X from D") is applied.
8. **Spending changes:** only flexible, non-protected series in categories the user allowed; max 3;
   smallest total cut wins (request_21 picks "stop backup + reduce streaming" (34.50) over "stop
   streaming" (47)).
9. **Images:** OCR + rules keyed on the event (balance due vs total vs net pay). Handles the ₹ glyph
   misread (₹79,679.26 -> 779,679.26) using the amount-in-words line, decimal commas ($33,50), Indian
   grouping (1,00,000.00), handwritten "4 543 00", and a "paid amount in words: Zero" trap. 16/16.

## Evaluation workflow

- `python3 code/evaluation/main.py` — per-column exact match (+1%/5% tolerance for astp), explanation
  similarity, verifier warnings, per-row diffs.
- `--sensitivity` — each calibrated knob scored separately on odd/even halves; all STABLE.
- Current: status 24/25, method 25/25, plan 24/25, earliest 22/25, changes 23/25, astp 15/25 within 5%.

## Honest limitations (say them before they are asked)

- `amount_safe_to_pay` exact on 6/25: per-category spend estimates differ from the reference by ~1-3%;
  when a row's decision is near a threshold that can flip earliest/plan (request_11, request_17).
- request_21: the reference seems to include two 21-day items before payday that my cadence puts just
  after it; I did not add a special case without a general reason.
- The Claude path is implemented and reached the API, but the account had no credits, so the final
  run used the rule parser and OCR. Output is identical in structure; the report states this.

## How I used AI while building

Built with Claude Code as a pair programmer: it read the spec and AGENTS.md, profiled the data,
wrote calibration/decoder scripts to reverse-engineer the reference behaviour from the 25 samples,
and implemented the engine; I directed priorities (free OCR instead of paid vision, private repo,
no hardcoded answers) and reviewed each decision. The transcript is `log.txt`.

## Likely questions — short answers

- *Why not let an LLM decide?* Exact numbers/dates; determinism; injection safety; cost.
- *How do you avoid overfitting?* Rules are general mechanisms, not per-row answers; split-half check.
- *What if a message contradicts the data?* Precedence: explicit amendment > newer record > settled >
  safer interpretation; e.g. unconfirmed bonus/commission/payout/refund is never counted.
- *How are installments validated?* Schedule rebuilt from first date + k·frequency, amounts copied
  verbatim, total ≤ max_installment_months, finishes by the deadline, safe on the forecast.
- *Currency?* Dated rate on the settlement date in the stated direction (inverse pairs differ).
