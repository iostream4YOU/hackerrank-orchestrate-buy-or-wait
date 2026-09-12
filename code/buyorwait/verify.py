"""Hard invariants checked on every row before output.csv is written."""
from decimal import Decimal

from .formatting import to_cents

STATUSES = {"affordable_now", "affordable_with_plan", "affordable_later", "not_affordable"}
METHODS = {"full_payment", "partial_payment", "installments", "wait", "not_recommended"}


def check(dec, ds, prof, fc) -> list:
    errs = []
    A, astp = dec.requested, dec.astp
    methods = {x for x in prof["payment_methods_user_will_consider"].split("|") if x}
    if not (Decimal(0) <= astp <= A):
        errs.append("astp out of bounds")
    if dec.status not in STATUSES or dec.method not in METHODS:
        errs.append("enum")
    dates = [dt for dt, _ in dec.plan]
    if any(b <= a for a, b in zip(dates, dates[1:])):
        errs.append("plan dates not strictly increasing")
    if dec.status == "affordable_now" and not (dec.earliest == dec.request_date and astp == A):
        errs.append("affordable_now invariant")
    if dec.status == "not_affordable" and dec.plan:
        errs.append("not_affordable invariant")
    if dec.earliest is not None and not fc.is_safe([(dec.earliest, float(A))]):
        errs.append("earliest date is not actually safe")
    if dec.method == "partial_payment":
        total = sum(to_cents(a) for _, a in dec.plan)
        if (dec.status != "affordable_with_plan" or len(dec.plan) != 2 or total != A
                or dec.earliest is None or dec.earliest > dec.desired_completion_date):
            errs.append("partial invariant")
    if dec.method == "installments":
        opt = dec.option
        if not opt or len(dec.plan) != int(opt["number_of_payments"]) or any(a != opt["payment_amount"] for _, a in dec.plan):
            errs.append("installments must match a supplied option")
    if dec.method == "wait" and (len(dec.plan) != 1 or dec.plan[0][0] != dec.earliest or "full_payment" not in methods):
        errs.append("wait invariant")
    if dec.method in ("full_payment", "partial_payment", "installments") and dec.method not in methods:
        errs.append("method not accepted by user")
    if len(dec.changes) > 3 or len({s.key for _, s, _ in dec.changes}) != len(dec.changes):
        errs.append("spending change count/uniqueness")
    for kind, s, _ in dec.changes:
        if s.flexibility == "fixed" or s.direction != "debit":
            errs.append(f"change on non-flexible {s.last_event_id}")
    if dec.method != "not_recommended":
        pays = [(dt, float(a)) for dt, a in dec.plan]
        changes = {s.key: (k, n) for k, s, n in dec.changes}
        if dec.method not in ("partial_payment",) and not fc.is_safe(pays, changes):
            errs.append("recommended plan not safe on forecast")
    return errs
