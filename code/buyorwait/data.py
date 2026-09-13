"""Loading and normalisation of the dataset/ CSV files.

Everything downstream works in the user's home currency. Foreign-currency cash
events are converted with the dated rate row for their settlement date, in the
stated from->to direction (both directions exist and are NOT exact inverses).
"""
from __future__ import annotations

import csv
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def d(s: str) -> date:
    return date.fromisoformat(s)


class FX:
    def __init__(self, rows):
        self.exact = {}
        self.by_pair = defaultdict(list)
        for r in rows:
            k = (r["from_currency"], r["to_currency"])
            self.exact[(r["rate_date"],) + k] = float(r["rate"])
            self.by_pair[k].append((r["rate_date"], float(r["rate"])))
        for k in self.by_pair:
            self.by_pair[k].sort()

    def rate(self, when: str, frm: str, to: str) -> float:
        if frm == to:
            return 1.0
        r = self.exact.get((when, frm, to))
        if r is not None:
            return r
        pts = self.by_pair.get((frm, to))
        if pts:  # nearest earlier dated rate, else the earliest available
            earlier = [v for dt, v in pts if dt <= when]
            return earlier[-1] if earlier else pts[0][1]
        inv = self.by_pair.get((to, frm))
        if inv:
            earlier = [v for dt, v in inv if dt <= when]
            return 1.0 / (earlier[-1] if earlier else inv[0][1])
        raise KeyError(f"no FX rate {frm}->{to} for {when}")


@dataclass
class Event:
    event_id: str
    user_id: str
    event_type: str
    description: str
    category: str
    direction: str
    amount: float | None      # home currency; None when blank and not yet resolved
    raw_amount: str
    currency: str
    event_date: date
    settlement_date: date | None
    status: str
    linked_event_id: str
    flexibility: str
    minimum_allowed_amount: float | None
    amount_source: str = "csv"  # csv | image


@dataclass
class Dataset:
    root: str
    profiles: dict
    events_by_user: dict
    events_by_id: dict
    requests: list
    samples: list
    options_by_request: dict
    messages: list
    images: list
    fx: FX
    output_columns: list = field(default_factory=list)


def load(dataset_dir: str) -> Dataset:
    p = lambda name: os.path.join(dataset_dir, name)
    fx = FX(read_csv(p("exchange_rates.csv")))
    profiles = {r["user_id"]: r for r in read_csv(p("financial_profiles.csv"))}

    events_by_user, events_by_id = defaultdict(list), {}
    for r in read_csv(p("financial_events.csv")):
        home = profiles[r["user_id"]]["home_currency"]
        when = r["settlement_date"] or r["event_date"]
        amt = None
        if r["amount"].strip():
            amt = float(r["amount"]) * fx.rate(when, r["currency"], home)
        e = Event(
            event_id=r["event_id"], user_id=r["user_id"], event_type=r["event_type"],
            description=r["description"], category=r["category"], direction=r["direction"],
            amount=amt, raw_amount=r["amount"], currency=r["currency"],
            event_date=d(r["event_date"]),
            settlement_date=d(r["settlement_date"]) if r["settlement_date"] else None,
            status=r["status"], linked_event_id=r["linked_event_id"], flexibility=r["flexibility"],
            minimum_allowed_amount=float(r["minimum_allowed_amount"]) if r["minimum_allowed_amount"] else None,
        )
        events_by_user[e.user_id].append(e)
        events_by_id[e.event_id] = e

    options = defaultdict(list)
    for r in read_csv(p("request_payment_options.csv")):
        options[r["request_id"]].append(r)

    with open(p("output.csv"), newline="", encoding="utf-8") as f:
        output_columns = next(csv.reader(f))

    return Dataset(
        root=dataset_dir, profiles=profiles, events_by_user=dict(events_by_user),
        events_by_id=events_by_id, requests=read_csv(p("requests.csv")),
        samples=read_csv(p("sample_requests.csv")), options_by_request=dict(options),
        messages=read_csv(p("messages.csv")), images=read_csv(p("images.csv")), fx=fx,
        output_columns=output_columns,
    )


def split_set(s: str) -> set:
    return {x.strip() for x in s.split("|") if x.strip()}
