"""Evaluation workflow: run the agent on dataset/sample_requests.csv and score
every output column against the labelled answers.

    python3 code/evaluation/main.py            # summary + per-row diffs
    python3 code/evaluation/main.py --brief    # summary only
"""
import argparse
import os
import sys
from difflib import SequenceMatcher

HERE = os.path.dirname(os.path.abspath(__file__))
CODE = os.path.dirname(HERE)
REPO = os.path.dirname(CODE)
sys.path.insert(0, CODE)

from buyorwait import data  # noqa: E402
from buyorwait.pipeline import OUTPUT_COLUMNS, solve_request  # noqa: E402

EXACT = ["affordability_status", "recommended_payment_method", "payment_plan",
         "earliest_date_for_full_payment", "spending_changes_needed"]


def astp_close(pred, gold, rel):
    p, g = float(pred), float(gold)
    return abs(p - g) <= rel * max(abs(g), 1e-9) + 0.005


def _cells(ds, evidence, rows):
    n = 0
    for gold in rows:
        row, _ = solve_request(ds, gold, evidence)
        n += sum(row[c] == gold[c] for c in EXACT + ["amount_safe_to_pay"])
    return n


def sensitivity(ds, evidence):
    """Overfitting check for every calibrated knob: score each alternative separately on the
    odd- and even-indexed halves of the samples. A knob is only trusted if its chosen value is
    (jointly) best on BOTH halves, i.e. the choice would have been made from either half alone."""
    from buyorwait import forecast as F
    halves = {"A": ds.samples[0::2], "B": ds.samples[1::2]}
    knobs = {
        "HORIZON_DAYS": [80, 84, 86, 88, 90],
        "ROUNDING": ["ceil", "round", "none"],
        "SHORT_CADENCE_RULE": ["interrupted", "keep", "drop"],
        "ORDER": ["net", "debits_first", "cadence_first"],
    }
    print("knob sensitivity (exact cells per half; * = chosen value)")
    for knob, values in knobs.items():
        chosen = getattr(F, knob)
        res = {}
        for v in values:
            setattr(F, knob, v)
            res[v] = {h: _cells(ds, evidence, rows) for h, rows in halves.items()}
        setattr(F, knob, chosen)
        best = {h: max(r[h] for r in res.values()) for h in halves}
        stable = all(res[chosen][h] == best[h] for h in halves)
        cells = "  ".join(f"{'*' if v == chosen else ' '}{v}: A={r['A']} B={r['B']}" for v, r in res.items())
        print(f"  {knob:20} {'STABLE' if stable else 'UNSTABLE'} | {cells}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=os.path.join(REPO, "dataset"))
    ap.add_argument("--brief", action="store_true")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--sensitivity", action="store_true", help="split-half overfitting check of calibrated knobs")
    args = ap.parse_args()

    ds = data.load(args.dataset)
    try:
        from buyorwait.evidence import Evidence
        evidence = Evidence(ds, use_llm=not args.no_llm)
    except ImportError:
        evidence = None
    if args.sensitivity:
        sensitivity(ds, evidence)
        return

    n = len(ds.samples)
    score = {c: 0 for c in EXACT}
    astp_exact = astp_1 = astp_5 = 0
    expl_sim = 0.0
    verify_fail = 0
    lines = []
    for gold in ds.samples:
        req = {k: gold[k] for k in ("request_id", "user_id", "request_date", "request_type", "requested_amount",
                                     "desired_completion_date", "allows_partial_payment", "request_text")}
        row, errs = solve_request(ds, req, evidence)
        verify_fail += bool(errs)
        diffs = []
        if row["amount_safe_to_pay"] == gold["amount_safe_to_pay"]:
            astp_exact += 1
        else:
            diffs.append(f"astp {row['amount_safe_to_pay']} vs {gold['amount_safe_to_pay']}")
        astp_1 += astp_close(row["amount_safe_to_pay"], gold["amount_safe_to_pay"], 0.01)
        astp_5 += astp_close(row["amount_safe_to_pay"], gold["amount_safe_to_pay"], 0.05)
        for c in EXACT:
            if row[c] == gold[c]:
                score[c] += 1
            else:
                diffs.append(f"{c}: {row[c] or '∅'} vs {gold[c] or '∅'}")
        expl_sim += SequenceMatcher(None, row["decision_explanation"], gold["decision_explanation"]).ratio()
        if diffs or errs:
            lines.append(f"{gold['request_id']} {gold['user_id']}: " + " | ".join(diffs) + (f" | VERIFY {errs}" if errs else ""))

    print(f"samples: {n}")
    print(f"  amount_safe_to_pay   exact {astp_exact}/{n}   within1% {astp_1}/{n}   within5% {astp_5}/{n}")
    for c in EXACT:
        print(f"  {c:30} {score[c]}/{n}")
    print(f"  decision_explanation similarity  {expl_sim / n:.3f}")
    print(f"  verifier warnings    {verify_fail}")
    all_exact = sum(score.values()) + astp_exact
    print(f"  TOTAL exact cells    {all_exact}/{n * (len(EXACT) + 1)}")
    if not args.brief:
        print("\n".join(lines))


if __name__ == "__main__":
    main()
