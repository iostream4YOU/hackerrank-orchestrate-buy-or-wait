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
- Models are used only where language/vision is needed: Gemini (free AI Studio tier, JSON-schema output)
  turns each message into typed facts and reads each receipt/bill image. Calls are batched (25 messages
  or 6 images per call): the full run is ~10 calls, ~100k tokens, $0. Free keys allow ~20 requests per
  model per day, so batching is what made it work; a daily-quota refusal falls through to the next model.
- Final run (usage report): 10 Gemini calls, 67,791 tokens, $0. The free Flash models' daily quotas were
  used up during development, so the run fell back to `gemini-3.1-flash-lite`. Images: model and OCR agree
  on 11/11. Messages: 142/198 model readings agree with the rule parser; the other 56 (mostly the lighter
  model labelling "first salary" as one-time, or "regular salary + arrears" as salary-continues) keep the
  parser reading and are listed. With `gemini-3.6-flash` agreement was 166/198. Output is identical
  either way - that is the point of the guard. The guard
  also found a parser bug (a message with two dates: a receipt date and a salary date) that the model
  read correctly - fixed.
- Every model reading passes an independent guard: a bilingual rule parser for messages and on-device
  OCR for images. Agreement -> the model's facts are used; disagreement -> the conservative reading is
  kept and logged in the usage report. Exact-match scoring makes a two-reader check worth it.
- Safety by construction: message text never reaches a decision prompt; outputs are schema-validated;
  instruction-bearing messages (the planted "pay the release charge today" scam) change nothing.
- Cost: $0 - Gemini free tier for the model calls, OCR on-device, everything else is code. The same
  interface supports Claude (`claude-opus-5`) when a funded key is present; a key/billing error falls
  through to the next provider. Model readings are cached by content hash and shipped, so the output
  reproduces without keys.

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
9. **Earliest date is capacity, not preference.** The spec says it is independent of payment preferences
   and blank only if no single full payment becomes safe in the window, so not-affordable rows still
   report it when capacity exists (e.g. an installments-only user whose options are unsafe).
10. **Spending changes apply to installments too.** 22 installments-only requests fail by 1-18% and are
    rescued by one small permitted cut that just covers the shortfall - the same signature as the
    full-payment-with-changes samples (short 17.10 / cut 19; short 31.05 / cut 34.50). Change plans
    always rank below no-change plans (rule 2).
11. **Installment cap = number of monthly payments** (3 payments 31 days apart fit a 3-month cap).
12. **Payday ordering:** weekly/biweekly spending on a payday is taken before the salary lands; monthly
    bills after it. It fixed four samples' astp (26%->8%, 11%->0.7%, 18%->0.9%, 10%->0.5%) and improved
    both halves of the split-half check without changing any categorical cell.
13. **Images:** OCR + rules keyed on the event (balance due vs total vs net pay). Handles the ₹ glyph
   misread (₹79,679.26 -> 779,679.26) using the amount-in-words line, decimal commas ($33,50), Indian
   grouping (1,00,000.00), handwritten "4 543 00", and a "paid amount in words: Zero" trap. 16/16.

## Evaluation workflow

- `python3 code/evaluation/main.py` — per-column exact match (+1%/5% tolerance for astp), explanation
  similarity, verifier warnings, per-row diffs.
- `--sensitivity` — each calibrated knob scored separately on odd/even halves; all STABLE.
- Current: status 24/25, method 25/25, plan 24/25, earliest 22/25, changes 23/25, astp 12/25 within 1%
  and 18/25 within 5%.

## Honest limitations (say them before they are asked)

- `amount_safe_to_pay` exact on 6/25: per-category spend estimates differ from the reference by ~1-3%;
  when a row's decision is near a threshold that can flip earliest/plan (request_11, request_17).
- request_21: the reference seems to include two 21-day items before payday that my cadence puts just
  after it; I did not add a special case without a general reason.
- The Claude path is implemented but the Anthropic account had no credit, so the final run used Gemini
  (free tier). The usage report shows the real Gemini calls and tokens.

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
  verbatim, number of payments ≤ max_installment_months, finishes by the deadline, safe on the forecast.
- *Currency?* Dated rate on the settlement date in the stated direction (inverse pairs differ).
