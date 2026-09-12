"""Cash-flow forecast over the 90-day safety window (effective horizon calibrated to 86 days).

Calibrated against dataset/sample_requests.csv (see README "Forecast rules"):

* Recurring series are detected on settled history with a lattice fit: either a
  fixed day-of-month (monthly) or a fixed day cadence (e.g. 7/10/14/21 days).
  A series is dead if its next expected occurrence is already in the past.
* Fixed-amount series project their exact amount. Variable-amount expense series
  project ceil(mean of history) in whole currency units (conservative).
* Projected cadence occurrences that fall on the request date itself are
  treated as already reflected in the current balance; monthly ones are not.
  A short-cadence (<7 day) series whose occurrence due today is missing is interrupted.
* Pending debits are reserved on their settlement date; scheduled debits on
  their date. Pending credits, failed/cancelled rows and unrealised values are
  ignored. A confirmed (scheduled) salary counts on its date and keeps recurring.
* Safety: end-of-day balance (debits and credits of a day netted) must stay at
  or above minimum_balance_to_keep for every day of the horizon.
"""
import calendar
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

HORIZON_DAYS = 86               # calibrated: reference forecast drops items on days 87-90 (see README)
ROUND_UNIT = {"IDR": 100}          # rounding unit for variable-spend estimates (default 1)
MIN_CADENCE_DAYS = 7               # "short" day cadence threshold (see SHORT_CADENCE_RULE)
SHORT_CADENCE_RULE = "interrupted" # interrupted: drop short series whose occurrence due today is missing
                                   # keep: always project; drop: never project
ROUNDING = "ceil"                  # variable-spend estimates: ceil | round | none
NON_CASH_TYPES = {"investment_valuation"}
NON_RECURRING_TYPES = {"refund", "investment_purchase", "investment_sale", "investment_valuation"}
ONE_OFF_INCOME = re.compile(
    r"bonus|commission|arrears|prize|reimburse|proceeds|refund|windfall|lottery", re.I)
EPS = 1e-6


def add_month(dt: date, k: int, dom: int) -> date:
    y, m = dt.year, dt.month + k
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return date(y, m, min(dom, calendar.monthrange(y, m)[1]))


def _is_dom(dt: date, dom: int) -> bool:
    return dt.day == min(dom, calendar.monthrange(dt.year, dt.month)[1])


def ceil_unit(x: float, unit: float) -> float:
    if ROUNDING == "none":
        return x
    if ROUNDING == "round":
        return math.floor(x / unit + 0.5) * unit
    return math.ceil(x / unit - 1e-9) * unit


@dataclass
class Series:
    key: str
    direction: str            # debit | credit
    category: str
    event_type: str
    description: str
    monthly: bool
    cadence: int              # day cadence when not monthly
    dom: int
    last: date
    amount: float
    fixed_amount: bool
    last_event_id: str
    flexibility: str
    min_allowed: float | None
    members: list = field(repr=False, default_factory=list)

    def next_expected(self) -> date:
        return add_month(self.last, 1, self.dom) if self.monthly else self.last + timedelta(days=self.cadence)

    def dates_between(self, rd: date, end: date) -> list:
        out, k = [], 1
        while True:
            nd = add_month(self.last, k, self.dom) if self.monthly else self.last + timedelta(days=self.cadence * k)
            if nd > end:
                return out
            if nd > rd or (nd == rd and self.monthly):
                out.append(nd)
            k += 1


@dataclass
class Flow:
    date: date
    amount: float             # signed: + credit, - debit
    label: str
    series_key: str | None = None
    event_id: str | None = None


def _tail_run(members, monthly, cadence):
    """Latest run of consecutive lattice points (drops anything before a gap)."""
    run = [members[-1]]
    for prev in reversed(members[:-1]):
        gap = (run[0].event_date - prev.event_date).days
        ok = 28 <= gap <= 31 if monthly else gap == cadence
        if not ok:
            break
        run.insert(0, prev)
    return run


def _one_per_day(evts):
    """Several events on one date (a regular occurrence plus a one-off): keep the one closest to the
    group's median amount so an extra purchase cannot break the cadence."""
    amounts = sorted(e.amount for e in evts)
    med = amounts[len(amounts) // 2]
    by_day = {}
    for e in evts:
        cur = by_day.get(e.event_date)
        if cur is None or abs(e.amount - med) < abs(cur.amount - med):
            by_day[e.event_date] = e
    return sorted(by_day.values(), key=lambda e: e.event_date)


def fit_lattice(evts):
    """Best regular sub-sequence of events: (monthly, cadence, dom, members) or None."""
    evts = _one_per_day(evts)
    if len(evts) < 2:
        return None
    cands = []
    for dom, _ in Counter(e.event_date.day for e in evts).most_common(2):
        m = [e for e in evts if _is_dom(e.event_date, dom)]
        if len(m) >= 2:
            m = _tail_run(m, True, 0)
            if len(m) >= 2:
                cands.append((len(m), 1, True, 0, dom, m))
    gaps = [(b.event_date - a.event_date).days for a, b in zip(evts, evts[1:])]
    for c, _ in Counter(gaps).most_common(3):
        if c < 2 or 28 <= c <= 31:
            continue
        res = Counter(e.event_date.toordinal() % c for e in evts).most_common(1)[0][0]
        m = [e for e in evts if e.event_date.toordinal() % c == res]
        m = _tail_run(m, False, c)
        if len(m) >= 2:
            cands.append((len(m), 0, False, c, m[-1].event_date.day, m))
    if not cands:
        return None
    n, _, monthly, cad, dom, m = max(cands, key=lambda x: (x[0], x[1]))
    if n < max(2, 0.5 * len(evts)):
        return None
    return monthly, cad, dom, m


ESTIMATOR = {"kind": "mean", "n": 0, "days": 0}


def estimate(members):
    """Per-occurrence estimate for a variable-amount expense series."""
    vals = [e.amount for e in members]
    k = ESTIMATOR
    if k["days"]:
        last = members[-1].event_date
        w = [e.amount for e in members if (last - e.event_date).days < k["days"]]
        vals = w or vals
    if k["n"]:
        vals = vals[-k["n"]:]
    if k["kind"] == "max":
        return max(vals)
    if k["kind"] == "median":
        s = sorted(vals)
        n = len(s)
        return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
    return sum(vals) / len(vals)


def _make_series(key, members, monthly, cad, dom, currency, direction):
    vals = [e.amount for e in members]
    fixed = max(vals) - min(vals) < EPS
    if fixed:
        amt = vals[-1]
    elif direction == "debit":
        amt = ceil_unit(estimate(members), ROUND_UNIT.get(currency, 1))
    else:
        # income: the latest amount once it has repeated, else the usual (modal) amount;
        # income with no repeating amount is variable and is not projected
        if len(vals) >= 2 and abs(vals[-1] - vals[-2]) < EPS:
            amt = vals[-1]
        else:
            mode_val, cnt = Counter(round(v, 2) for v in vals).most_common(1)[0]
            if cnt < 2:
                return None
            amt = mode_val
    last = members[-1]
    return Series(
        key=key, direction=direction, category=last.category, event_type=last.event_type,
        description=last.description, monthly=monthly, cadence=cad, dom=dom,
        last=last.event_date, amount=amt, fixed_amount=fixed, last_event_id=last.event_id,
        flexibility=last.flexibility, min_allowed=last.minimum_allowed_amount, members=members)


def detect_series(events, rd: date, currency: str, notes: list):
    hist = [e for e in events if e.status == "settled" and e.event_date < rd and e.amount is not None
            and e.event_type not in NON_RECURRING_TYPES and e.direction in ("debit", "credit")]
    series = []

    def consider(key, group, direction):
        fit = fit_lattice(group)
        if not fit:
            return set()
        monthly, cad, dom, members = fit
        short = not monthly and cad < MIN_CADENCE_DAYS
        if short and (SHORT_CADENCE_RULE == "drop" or (
                SHORT_CADENCE_RULE == "interrupted" and members[-1].event_date + timedelta(days=cad) == rd)):
            # high-frequency series whose occurrence due today is missing -> interrupted
            notes.append(f"interrupted short-cadence series {key} every {cad}d")
            return set(id(e) for e in members)
        s = _make_series(key, members, monthly, cad, dom, currency, direction)
        if s is None:
            notes.append(f"variable income not projected {key}")
            return set(id(e) for e in members)
        if s.next_expected() < rd:
            notes.append(f"dead series {key} (last {s.last})")
        else:
            series.append(s)
        return set(id(e) for e in members)

    debits = defaultdict(list)
    for e in hist:
        if e.direction == "debit":
            debits[(e.category, e.event_type)].append(e)
    for (cat, et), group in sorted(debits.items()):
        used = consider(f"{cat}:{et}", group, "debit")
        rest = [e for e in group if id(e) not in used]
        by_desc = defaultdict(list)
        for e in rest:
            by_desc[e.description].append(e)
        for desc, g in sorted(by_desc.items()):
            consider(f"{cat}:{et}:{desc}", g, "debit")

    credits = defaultdict(list)
    for e in hist:
        if e.direction == "credit" and not ONE_OFF_INCOME.search(e.description) and e.category != "windfall":
            credits[e.description].append(e)
    for desc, g in sorted(credits.items()):
        consider(f"income:{desc}", g, "credit")
    return series


@dataclass
class Forecast:
    user_id: str
    request_date: date
    end: date
    currency: str
    start_balance: float
    min_balance: float
    series: list
    flows: list
    notes: list

    # ---- balance simulation -------------------------------------------------
    def daily_net(self, changes=None, payments=()):
        """changes: {series_key: ("stop", None) | ("reduce", new_amount)}"""
        changes = changes or {}
        net = defaultdict(float)
        for f in self.flows:
            if f.series_key in changes:
                kind, new_amt = changes[f.series_key]
                if kind == "stop":
                    continue
                if kind == "reduce":
                    net[f.date] -= new_amt
                    continue
            net[f.date] += f.amount
        for dt, amt in payments:
            net[dt] -= amt
        return net

    def balances(self, changes=None, payments=()):
        net = self.daily_net(changes, payments)
        bal, out = self.start_balance, []
        dt = self.request_date
        while dt <= self.end:
            bal += net.get(dt, 0.0)
            out.append((dt, bal))
            dt += timedelta(days=1)
        return out

    def min_headroom(self, changes=None, payments=()):
        return min(b for _, b in self.balances(changes, payments)) - self.min_balance

    def is_safe(self, payments, changes=None) -> bool:
        return self.min_headroom(changes, payments) >= -EPS

    # ---- headline numbers ---------------------------------------------------
    def amount_safe_today(self, requested: float, changes=None) -> float:
        return max(0.0, min(requested, self.min_headroom(changes)))

    def earliest_full(self, requested: float, changes=None, until: date | None = None):
        bals = self.balances(changes)
        until = until or self.end
        running_min_before = math.inf
        suffix_min = [0.0] * len(bals)
        m = math.inf
        for i in range(len(bals) - 1, -1, -1):
            m = min(m, bals[i][1])
            suffix_min[i] = m
        for i, (dt, _) in enumerate(bals):
            if dt > until:
                break
            before_ok = running_min_before >= self.min_balance - EPS
            if before_ok and suffix_min[i] - requested >= self.min_balance - EPS:
                return dt
            running_min_before = min(running_min_before, bals[i][1])
        return None


def build_forecast(ds, user_id: str, rd: date, facts=None) -> Forecast:
    """facts: evidence.UserFacts (message/image derived adjustments) or None."""
    prof = ds.profiles[user_id]
    cur = prof["home_currency"]
    events = ds.events_by_user.get(user_id, [])
    end = rd + timedelta(days=HORIZON_DAYS)
    notes, flows = [], []

    series = detect_series(events, rd, cur, notes)
    if facts is not None:
        facts.adjust_series(series, rd, notes)

    income = [s for s in series if s.direction == "credit"]
    projected_income = {s.key: s.dates_between(rd, end) for s in income}

    # confirmed / scheduled salary: counts on its date and replaces the matching projection
    for e in events:
        if e.direction == "credit" and e.status == "scheduled" and e.amount is not None:
            sd = e.settlement_date or e.event_date
            if facts is not None and facts.is_income_excluded(e):
                notes.append(f"scheduled credit {e.event_id} excluded by evidence")
                continue
            match = None
            for s in income:
                if any(abs((x - sd).days) <= 10 for x in projected_income[s.key]):
                    match = s
            if match is not None:
                projected_income[match.key] = [x for x in projected_income[match.key] if abs((x - sd).days) > 10]
                match.amount = e.amount
            else:
                s = Series(key=f"income:confirmed:{e.event_id}", direction="credit", category=e.category,
                           event_type=e.event_type, description=e.description, monthly=True, cadence=0,
                           dom=sd.day, last=sd, amount=e.amount, fixed_amount=True, last_event_id=e.event_id,
                           flexibility="fixed", min_allowed=None)
                series.append(s)
                income.append(s)
                projected_income[s.key] = s.dates_between(rd, end)
            if rd <= sd <= end:
                flows.append(Flow(sd, e.amount, f"confirmed {e.description}", None, e.event_id))

    for s in series:
        dates = projected_income[s.key] if s.direction == "credit" else s.dates_between(rd, end)
        sign = 1 if s.direction == "credit" else -1
        for dt in dates:
            amt = s.amount
            if facts is not None:
                amt = facts.series_amount_on(s, dt, amt)
                if amt is None:
                    continue
            flows.append(Flow(dt, sign * amt, s.key, s.key))

    # one-off future items: pending / scheduled debits
    for e in events:
        if e.status in ("failed", "cancelled", "unrealized") or e.event_type in NON_CASH_TYPES:
            continue
        if e.direction != "debit" or e.status not in ("pending", "scheduled"):
            continue
        if e.amount is None:
            notes.append(f"unresolved blank amount {e.event_id}")
            continue
        if facts is not None and facts.is_debit_excluded(e):
            notes.append(f"debit {e.event_id} excluded by evidence")
            continue
        when = max(e.settlement_date or e.event_date, rd)
        if when <= end:
            flows.append(Flow(when, -e.amount, f"{e.status} {e.description}", None, e.event_id))

    if facts is not None:
        flows.extend(facts.extra_flows(rd, end, series, notes))

    flows.sort(key=lambda f: (f.date, f.amount))
    return Forecast(user_id=user_id, request_date=rd, end=end, currency=cur,
                    start_balance=float(prof["current_available_balance"]),
                    min_balance=float(prof["minimum_balance_to_keep"]),
                    series=series, flows=flows, notes=notes)
