"""Deterministic decision explanations in the voice of the labelled samples:
imperative first sentence, then the binding financial fact."""
from .formatting import fmt_money_text as money, fmt_date_text as human


def _change_phrase(changes, cur):
    parts = []
    for kind, s, new_amt in changes:
        name = s.description[0].lower() + s.description[1:]
        if kind == "stop":
            parts.append(f"stop the {name}")
        else:
            parts.append(f"reduce the {name} to {money(new_amt, cur)}")
    text = " and ".join(parts) if len(parts) <= 2 else ", ".join(parts[:-1]) + " and " + parts[-1]
    return text[0].upper() + text[1:]


def explain(dec) -> str:
    cur, A, mn = dec.currency, dec.requested, dec.min_balance
    if dec.method == "full_payment" and not dec.changes:
        return (f"Pay {money(A, cur)} today. This leaves at least {money(mn, cur)} available "
                f"over the next 90 days.")
    if dec.method == "full_payment":
        return (f"{_change_phrase(dec.changes, cur)}, then pay {money(A, cur)} today. "
                f"This leaves at least {money(mn, cur)} available.")
    if dec.method == "installments":
        n = len(dec.plan)
        amt = dec.plan[0][1]
        return (f"Use {n} installments of {money(amt, cur)}, starting {human(dec.plan[0][0])}. "
                f"This leaves at least {money(mn, cur)} available.")
    if dec.method == "partial_payment":
        (d1, a1), (d2, a2) = dec.plan
        return (f"Pay {money(a1, cur)} today and the remaining {money(a2, cur)} on {human(d2)}. "
                f"This completes the full request and keeps the {money(mn, cur)} minimum protected.")
    if dec.method == "wait":
        return (f"Pay {money(A, cur)} in full on {human(dec.plan[0][0])}. Paying earlier would take "
                f"the balance below the {money(mn, cur)} minimum.")
    if dec.astp > 0 and "partial_considered" in dec.notes:
        return (f"Do not proceed with the {money(A, cur)} request. Although {money(dec.astp, cur)} is "
                f"available today, the full amount cannot be completed safely within 90 days.")
    return (f"Do not make this payment by {human(dec.desired_completion_date)}. None of the available "
            f"options keeps the {money(mn, cur)} minimum protected.")
