# Buy or Wait? — affordability agent

For every row of `dataset/requests.csv` the agent reconstructs the user's cash position, forecasts
the next ~90 days, searches every eligible payment plan, verifies it, and writes one row of
`output.csv` in the exact required schema.

**Design in one line:** deterministic code does all money math; untrusted messages and images are only
ever turned into typed facts (on-device OCR for images; a Claude call or a bilingual rule parser for
messages). The scoring is exact-match on numbers, dates and enums, and a day-by-day balance simulation
over 250 users is exactly the kind of work code gets right and a model approximates.

```
dataset/*.csv ──► normalise (FX, joins) ──► evidence: images ─► on-device OCR + amount rules
                                         │             messages ─► typed facts (Claude JSON schema | rule parser)
                                         │                               │ (untrusted: never reaches decisions)
                                         ▼                               ▼
                               recurring-series detection ──► 90-day cash-flow forecast ◄── fact adjustments
                                         │
          baseline forecast ─► amount_safe_to_pay, earliest_date_for_full_payment
          plan search ─► full / installments (supplied options) / partial / wait / full+spending changes
          rank (problem-statement order) ─► verify invariants ─► explanation ─► output.csv
```

## Quick start

```bash
# from the repository root
python3 -m venv .venv
.venv/bin/pip install -r code/requirements.txt
cp code/.env.example .env        # optional: a funded key enables the Claude path (never commit it)
.venv/bin/python code/main.py    # -> ./output.csv and code/evaluation/usage_report.md
```

| command | what it does |
|---|---|
| `python3 code/main.py` | full run on `dataset/requests.csv` -> `output.csv` + usage report |
| `python3 code/main.py --refresh` | ignore the evidence cache and re-query the model for every message/image |
| `python3 code/main.py --no-llm` | no API calls: cached facts, else the rule-based parser |
| `python3 code/evaluation/main.py` | score every output column against `dataset/sample_requests.csv` |
| `python3 code/evaluation/main.py --sensitivity` | split-half overfitting check of every calibrated knob |

Python 3.10+. The engine is standard library; `anthropic` is needed only for the optional model path.
Image OCR uses Apple Vision via the Xcode command-line tools (`swiftc`) on macOS, else the `tesseract` CLI.
Credentials are read from the environment or a `.env` file: `ANTHROPIC_API_KEY` (and
`ANTHROPIC_WORKSPACE_ID` only for keys that are not workspace-scoped). The model defaults to
`claude-opus-5`; override with `BUYORWAIT_MODEL`.

**No key is required.** Images are read with free on-device OCR (Apple Vision on macOS, compiled from
`buyorwait/ocr_vision.swift` on first use; Tesseract elsewhere) and messages by the bilingual rule
parser, so the default run costs $0. With a funded key, Claude interprets messages (cross-checked
against the parser) and reads any image the OCR rules cannot decide; results are cached in
`code/cache/evidence_cache.json` by content hash.

## Forecast rules

All rules were derived from, and are regression-tested against, the 25 labelled samples.

| rule | detail |
|---|---|
| currency | every cash event converted to `home_currency` with the dated rate for its settlement date, in the stated from→to direction (both directions exist and are not exact inverses) |
| recurring series | settled history grouped by category (by description for income and leftovers) and fitted to a lattice: fixed day-of-month, or a fixed day cadence (7/10/14/21…). One-off events off the lattice are ignored. |
| dead series | a series whose next expected occurrence is already in the past has stopped (final payroll, ended household income, cancelled subscription) |
| expense amounts | fixed-amount series project exactly; variable ones project `ceil(mean)` in whole units (IDR: 100) — "forecast essential variable spending conservatively" |
| income amounts | the latest amount once it has repeated, otherwise the modal amount; income with no repeating amount (gig payouts, commissions, freelance) is not projected |
| confirmed salary | a scheduled "Next confirmed salary" counts on its date, replaces the nearby projection, and the salary keeps recurring monthly |
| pending / scheduled | pending debits reserved on settlement date; scheduled debits (bill retries, school fees, outstanding balances) on their date; pending credits, failed/cancelled rows and unrealised values ignored |
| request day | a cadence occurrence due on the request date is already reflected in the balance; a monthly one is not; a <7-day series whose occurrence due today is missing is treated as interrupted |
| horizon | the reference drops items on days 87–90 of the window (3 no-income samples each lose exactly their third rent there); the forecast covers 86 days. Stable on both halves of the samples. |
| safety | end-of-day balance (debits and credits of a day netted) must stay ≥ `minimum_balance_to_keep` on every day |

**Two forecasts per request.** `amount_safe_to_pay` (largest payment today that stays safe) and
`earliest_date_for_full_payment` (first day a single full payment stays safe to the horizon) use the
baseline with **no** spending changes and ignore payment preferences. The recommendation may apply
permitted changes. This is why rows like `request_06` legitimately show `earliest` after the deadline
alongside "stop X, then pay in full today".

## Decision logic

Candidates, each only if eligible (method in `payment_methods_user_will_consider`) and safe:

1. full payment today;
2. every supplied installment option whose number of (monthly) payments is within `max_installment_months` and that finishes by the deadline — the plan is the option's schedule verbatim (`first_payment_date + k·frequency`, `payment_amount` string copied);
3. partial payment: `amount_safe_to_pay` today and the rest on `earliest_date_for_full_payment`, when allowed, accepted, `0 < astp < requested` and earliest ≤ deadline;
4. wait until the earliest safe date (needs `full_payment` accepted and earliest ≤ deadline);
5. full payment today, or a supplied installment schedule, made safe by ≤3 permitted spending changes: only flexible, non-protected series in a category the user agreed to reduce (`reduce_to` its minimum allowed amount) or stop; one change per event; the combination with the **smallest total cut** wins (matches `request_21`), referencing the most recent event of the series. Plans that need changes always rank below plans that do not.

Ranking follows the problem statement: completes by the deadline → no spending changes → lowest total
paid → earliest start → fewest payments → lowest `payment_option_id`. (A fixed "installments before
partial" order is wrong: `request_19` picks partial because it costs less.) If nothing is safe:
`not_affordable` / `not_recommended`, plan `none`. `earliest_date_for_full_payment` still reports the
capacity date when one exists (it is preference-independent and blank only when no single full payment
becomes safe inside the window); the explanation then says why no accepted plan works.

## Evidence: messages and images (untrusted)

- **Messages** → a strict JSON schema (`intent`, `subject`, `scope`, `amount`, `currency`, `percent`,
  `effective_date`, `one_time_extra_amount`, `contains_instructions_to_reader`), produced by one Claude
  call per message when a funded key is configured, otherwise by the bilingual (EN/ID) rule parser,
  which covers every message template in the dataset. The model sees only the message text; it never
  sees balances, rules or the decision.
- **Images** → only for events whose `amount` is blank (never treated as zero). On-device OCR rebuilds
  label/value rows, then the amount is picked by the event's meaning: outstanding balance → *balance
  due*; bill → *amount due by the due date*; payslip → *net pay*; receipt → *grand total / total paid*
  (never cash tendered or change). Checks: amount-in-words cross-validation, the OCR misread of a
  leading ₹ as a digit (`₹79,679.26` → `779,679.26`) is undone only when the words or another printed
  figure confirm it, decimal commas (`$33,50`), Indian grouping (`1,00,000.00`), handwritten
  rupee/paise columns (`4 543 00`). 16/16 dataset images resolve to the figure a human reads. Claude
  vision is used only when OCR cannot decide.
- **Deterministic application** (`evidence.UserFacts`): raises from an effective date; temporary /
  reduced pay for the next payroll only; moved pay dates; confirmed first salaries; ended income
  streams; pending payouts/commissions/bonuses/refunds/prizes excluded; approved invoices as one-off
  credits; rent % increases from the next payment; failed bills reserved unless a retry is scheduled.
  A "confirmed base salary" figure is gross (it is exactly 1.67× the observed deposits), so it
  confirms the salary without changing it.
- **Prompt-injection defence:** messages such as "pay the release charge today to receive the funds"
  are classified `suspicious_instruction` and change nothing. No message or image text is ever placed
  in a prompt that makes a financial decision, and every model output is schema-validated.
- **Cross-check:** when the model runs, its primary intent is compared with the rule parser's for every
  message and disagreements are counted in the usage report.

## Verification

Every row is checked before it is written (`verify.py`): `0 ≤ astp ≤ requested`; enums valid;
chronological plan dates; `affordable_now ⇒ earliest = request_date ∧ astp = requested`;
`not_affordable ⇒ plan none`; any reported earliest date is re-checked as genuinely safe; partial = exactly 2 payments summing to the request by
the deadline; installments match a supplied option exactly; wait = one payment on the earliest date;
method accepted by the user; ≤3 changes, flexible only, one per event; the recommended plan is safe on
the forecast. The run also asserts one row per request and the exact column order of
`dataset/output.csv`.

## Evaluation

`code/evaluation/main.py` runs the full pipeline on `dataset/sample_requests.csv` and reports, per
column: exact match (and 1% / 5% tolerance for `amount_safe_to_pay`), explanation similarity and
verifier warnings, followed by a per-row diff. `--sensitivity` re-scores each calibrated knob
separately on the odd and even halves of the samples; a value is kept only if it is best on both
halves (currently all knobs are stable). Remaining gaps are mostly per-category spend estimates that
differ from the reference by ~1%.

### Results on the labelled samples (current build)

| column | exact match |
|---|---|
| `affordability_status` | 24 / 25 |
| `recommended_payment_method` | 25 / 25 |
| `payment_plan` | 24 / 25 |
| `earliest_date_for_full_payment` | 22 / 25 |
| `spending_changes_needed` | 23 / 25 |
| `amount_safe_to_pay` | 6 / 25 exact, 9 / 25 within 1%, 15 / 25 within 5% |
| explanation similarity to the label text | 0.93 |
| verifier warnings | 0 |

## Token usage

Each full run writes `code/evaluation/usage_report.md` with provider, model, calls, input/output
tokens, totals, per-request averages and estimated cost for exactly that run, plus how every message
and image was interpreted (model, cache, rule parser, OCR). Only evidence for users in the input file
is interpreted; the forecast, search, OCR and explanations cost nothing.

## Layout

```
code/
  main.py                 entry point (writes ../output.csv and evaluation/usage_report.md)
  buyorwait/data.py       CSV loading, FX conversion
  buyorwait/forecast.py   recurring-series detection, 90-day cash-flow simulation
  buyorwait/evidence.py   message/image interpretation (Claude | rule parser | OCR), fact application
  buyorwait/ocr.py        on-device OCR + deterministic amount selection (ocr_vision.swift helper)
  buyorwait/llm.py        Claude client, structured outputs, token/cost accounting
  buyorwait/planner.py    plan enumeration, spending-change search, ranking
  buyorwait/verify.py     hard invariants
  buyorwait/explain.py    grounded explanations in the label voice
  buyorwait/formatting.py exact number/date formats
  buyorwait/report.py     usage report
  evaluation/main.py      evaluation workflow + sensitivity check
  cache/                  evidence cache (model outputs keyed by content hash)
```
