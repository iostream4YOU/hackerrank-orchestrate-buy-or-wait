"""Recommendation logic on top of the forecast.

Two forecasts per request (see README):
  * baseline (no spending changes) -> amount_safe_to_pay, earliest_date_for_full_payment
  * adjusted (optional permitted spending changes) -> only used to rescue a
    full payment today when nothing better is safe.
"""
import itertools
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from .data import split_set, d
from .formatting import to_cents

MAX_CHANGES = 3
STOP_FLEX = {"stoppable", "reducible_or_stoppable"}
REDUCE_FLEX = {"reducible", "reducible_or_stoppable"}


@dataclass
class Decision:
    request_id: str
    currency: str
    requested: Decimal
    request_date: date
    desired_completion_date: date
    min_balance: float
    astp: Decimal
    status: str
    method: str
    plan: list                      # [(date, amount_str)]
    earliest: date | None
    changes: list                   # [(kind, series, new_amount|None)]
    option: dict | None = None
    notes: list = field(default_factory=list)


def _installment_schedule(opt):
    n = int(opt["number_of_payments"])
    first = d(opt["first_payment_date"])
    freq = int(opt["payment_frequency_days"] or 0)
    return [(first + timedelta(days=freq * k), opt["payment_amount"]) for k in range(n)]


def _installment_months(opt) -> float:
    n = int(opt["number_of_payments"])
    freq = int(opt["payment_frequency_days"] or 30)
    return n * freq / 30.0


def change_candidates(fc, prof):
    """All permitted single changes: (kind, series, new_amount, saving_over_window)."""
    protect = split_set(prof["expense_categories_to_protect"])
    can_reduce = split_set(prof["expense_categories_user_is_willing_to_reduce"])
    can_stop = split_set(prof["expense_categories_user_is_willing_to_stop"])
    out = []
    for s in fc.series:
        if s.direction != "debit" or s.category in protect:
            continue
        occ = [f for f in fc.flows if f.series_key == s.key]
        if not occ:
            continue
        if s.flexibility in STOP_FLEX and s.category in can_stop:
            out.append(("stop", s, None, sum(-f.amount for f in occ)))
        if (s.flexibility in REDUCE_FLEX and s.category in can_reduce and s.min_allowed is not None
                and s.min_allowed < s.amount - 1e-9):
            out.append(("reduce", s, s.min_allowed, sum(-f.amount - s.min_allowed for f in occ)))
    return out


def find_spending_changes(fc, prof, payments):
    """Smallest total cut (<=3 changes, one per event) that makes `payments` safe."""
    cands = change_candidates(fc, prof)
    best = None
    for r in range(1, MAX_CHANGES + 1):
        for combo in itertools.combinations(cands, r):
            keys = [c[1].key for c in combo]
            if len(set(keys)) < len(keys):
                continue
            changes = {c[1].key: (c[0], c[2]) for c in combo}
            if not fc.is_safe(payments, changes):
                continue
            cut = sum(c[3] for c in combo)
            rank = (round(cut, 6), r, sorted(c[1].last_event_id for c in combo))
            if best is None or rank < best[0]:
                best = (rank, combo)
    return list(best[1]) if best else None


def decide(ds, req, fc) -> Decision:
    prof = ds.profiles[req["user_id"]]
    M = split_set(prof["payment_methods_user_will_consider"])
    max_months = float(prof["max_installment_months"]) if prof["max_installment_months"] else None
    rd = d(req["request_date"])
    dcd = d(req["desired_completion_date"])
    A = to_cents(req["requested_amount"])
    Af = float(A)
    allows_partial = req["allows_partial_payment"].strip().lower() == "true"

    astp = to_cents(fc.amount_safe_today(Af))
    earliest = fc.earliest_full(Af)
    base = dict(request_id=req["request_id"], currency=fc.currency, requested=A, request_date=rd,
                desired_completion_date=dcd, min_balance=fc.min_balance, astp=astp, earliest=earliest)
    partial_wanted = "partial_payment" in M and allows_partial

    # Enumerate every eligible, safe plan; rank with the problem-statement order:
    # (1) completes by deadline (all candidates do), (2) no spending changes,
    # (3) lowest total paid, (4) earliest start, (5) fewest payments, (6) lowest option id.
    cands = []  # (rank_key, Decision)

    if "full_payment" in M and astp >= A:
        cands.append(((0, float(A), rd, 1, ""), Decision(
            **{**base, "earliest": rd}, status="affordable_now", method="full_payment",
            plan=[(rd, A)], changes=[])))

    if "installments" in M:
        for opt in ds.options_by_request.get(req["request_id"], []):
            if opt["payment_method"] != "installments":
                continue
            if max_months is not None and _installment_months(opt) > max_months + 1e-9:
                continue
            sched = _installment_schedule(opt)
            if sched[-1][0] > dcd or sched[0][0] < rd:
                continue
            if not fc.is_safe([(dt, float(a)) for dt, a in sched]):
                continue
            cands.append(((0, float(opt["total_payable_amount"]), sched[0][0], len(sched),
                           opt["payment_option_id"]),
                          Decision(**base, status="affordable_with_plan", method="installments",
                                   plan=sched, changes=[], option=opt)))

    if partial_wanted and Decimal(0) < astp < A and earliest is not None and earliest <= dcd:
        dec = Decision(**base, status="affordable_with_plan", method="partial_payment",
                       plan=[(rd, astp), (earliest, A - astp)], changes=[])
        if not fc.is_safe([(rd, float(astp)), (earliest, float(A - astp))]):
            dec.notes.append("partial plan not strictly safe on combined forecast")
        cands.append(((0, float(A), rd, 2, ""), dec))

    if "full_payment" in M and earliest is not None and rd < earliest <= dcd:
        cands.append(((0, float(A), earliest, 1, ""), Decision(
            **base, status="affordable_later", method="wait", plan=[(earliest, A)], changes=[])))

    if "full_payment" in M and astp < A:
        combo = find_spending_changes(fc, prof, [(rd, Af)])
        if combo:
            cands.append(((1, float(A), rd, 1, ""), Decision(
                **base, status="affordable_with_plan", method="full_payment", plan=[(rd, A)],
                changes=[(c[0], c[1], c[2]) for c in combo])))

    if cands:
        return min(cands, key=lambda x: x[0])[1]
    dec = Decision(**{**base, "earliest": None}, status="not_affordable", method="not_recommended",
                   plan=[], changes=[])
    dec.notes.append("partial_considered" if partial_wanted else "")
    return dec
