"""End-to-end: request rows -> verified output rows."""
from .data import d
from .explain import explain
from .forecast import build_forecast
from .formatting import fmt_astp, fmt_plan, fmt_plan_amount
from .planner import decide
from .verify import check

OUTPUT_COLUMNS = ["request_id", "amount_safe_to_pay", "affordability_status", "recommended_payment_method",
                  "payment_plan", "earliest_date_for_full_payment", "spending_changes_needed",
                  "decision_explanation"]


def fmt_changes(changes) -> str:
    if not changes:
        return "none"
    out = []
    for kind, s, new_amt in changes:
        out.append(f"stop:{s.last_event_id}" if kind == "stop" else
                   f"reduce_to:{s.last_event_id}:{fmt_plan_amount(new_amt)}")
    return "|".join(out)


def solve_request(ds, req, evidence=None, debug=False):
    facts = evidence.for_user(req["user_id"], req) if evidence is not None else None
    fc = build_forecast(ds, req["user_id"], d(req["request_date"]), facts)
    dec = decide(ds, req, fc)
    errs = check(dec, ds, ds.profiles[req["user_id"]], fc)
    row = {
        "request_id": req["request_id"],
        "amount_safe_to_pay": fmt_astp(dec.astp),
        "affordability_status": dec.status,
        "recommended_payment_method": dec.method,
        "payment_plan": fmt_plan(dec.plan),
        "earliest_date_for_full_payment": dec.earliest.isoformat() if dec.earliest else "",
        "spending_changes_needed": fmt_changes(dec.changes),
        "decision_explanation": explain(dec),
    }
    if debug:
        return row, dec, fc, errs
    return row, errs
