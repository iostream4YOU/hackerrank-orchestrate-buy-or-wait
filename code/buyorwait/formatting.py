"""Exact output formatting. Two different number formats are required:

* amount_safe_to_pay   -> 2dp, trailing zeros stripped   (603.3, 25256, 87170.56)
* payment_plan amounts -> integer if integral, else exactly 2dp (620.40, 25256)
"""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

_CENT = Decimal("0.01")


def to_cents(x) -> Decimal:
    return Decimal(str(x)).quantize(_CENT, rounding=ROUND_HALF_UP)


def fmt_astp(x) -> str:
    s = format(to_cents(x), "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def fmt_plan_amount(x) -> str:
    d = to_cents(x)
    return str(int(d)) if d == d.to_integral_value() else format(d, "f")


def fmt_money_text(x, currency: str) -> str:
    """Human amount for explanations: thousands separators, int if integral else 2dp."""
    d = to_cents(x)
    body = f"{int(d):,}" if d == d.to_integral_value() else f"{d:,.2f}"
    return f"{currency} {body}"


def fmt_date_text(d: date) -> str:
    return f"{d.day} {d.strftime('%B %Y')}"


def fmt_plan(payments) -> str:
    """payments: list of (date, amount_str_or_number). Amount strings are copied verbatim."""
    if not payments:
        return "none"
    parts = []
    for dt, amt in payments:
        a = amt if isinstance(amt, str) else fmt_plan_amount(amt)
        parts.append(f"{dt.isoformat()}:{a}")
    return "|".join(parts)
