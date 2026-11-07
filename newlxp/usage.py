"""Token and cost accounting for every AI request.

Tokens come from the provider and are always exact. Money does not: prices
change and differ per account, so a run is only priced when the model has an
entry in :func:`prices`. Everything is appended to a JSONL log, which makes
"what did this discipline cost me" a one-line question to answer.
"""
from __future__ import annotations

import json
import os
import time

LOG_FILE = os.path.join(os.path.expanduser("~"), ".newlxp_cache", "usage.jsonl")

# USD per million tokens, as published by the providers. Prices change, so
# these are a starting point and can be overridden per model in the config
# file under "prices": {"<model>": {"input": 0.15, "output": 0.60}}.
DEFAULT_PRICES = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
}


class Run:
    """One completion: which model, how many tokens, what it cost."""

    __slots__ = ("model", "input_tokens", "output_tokens", "label", "seconds")

    def __init__(self, model: str, input_tokens: int, output_tokens: int,
                 label: str = "", seconds: float = 0.0):
        self.model = model
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.label = label
        self.seconds = seconds

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def cost(self, prices: dict) -> float | None:
        """Cost in USD, or ``None`` when the model has no price configured."""
        price = prices.get(self.model)
        if not price:
            return None
        return (self.input_tokens * price.get("input", 0.0)
                + self.output_tokens * price.get("output", 0.0)) / 1_000_000

    def as_dict(self) -> dict:
        return {"time": int(time.time()), "model": self.model, "label": self.label,
                "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "seconds": round(self.seconds, 1)}


def prices(config: dict | None = None) -> dict:
    """Prices per million tokens: the defaults, overridden by the config."""
    merged = dict(DEFAULT_PRICES)
    custom = (config or {}).get("prices")
    if isinstance(custom, dict):
        merged.update({k: v for k, v in custom.items() if isinstance(v, dict)})
    return merged


def record(run: Run, path: str | None = None) -> bool:
    """Append a run to the usage log. Never raises; returns success.

    ``path`` defaults to :data:`LOG_FILE` at call time, not at import time,
    so a test can redirect the log instead of writing to the real one.
    """
    path = LOG_FILE if path is None else path
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(run.as_dict(), ensure_ascii=False) + "\n")
        return True
    except OSError:
        return False


def read_log(path: str | None = None) -> list:
    """Return the recorded runs, skipping any line that is not valid JSON."""
    path = LOG_FILE if path is None else path
    runs = []
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return runs
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("model"):
            runs.append(Run(row["model"], row.get("input_tokens", 0),
                            row.get("output_tokens", 0), row.get("label", ""),
                            row.get("seconds", 0.0)))
    return runs


def summarise(runs, price_table: dict) -> dict:
    """Totals across runs: requests, tokens and cost where it is known."""
    known = [r for r in runs if r.cost(price_table) is not None]
    return {
        "requests": len(runs),
        "input_tokens": sum(r.input_tokens for r in runs),
        "output_tokens": sum(r.output_tokens for r in runs),
        "total_tokens": sum(r.total_tokens for r in runs),
        "cost": sum(r.cost(price_table) for r in known) if known else None,
        "priced_requests": len(known),
    }


def format_run(run: Run, price_table: dict) -> str:
    """One-line summary for the interface: tokens, and money when known."""
    cost = run.cost(price_table)
    text = "%s in + %s out = %s tokens" % (
        _group(run.input_tokens), _group(run.output_tokens), _group(run.total_tokens))
    return text + (", $%.4f" % cost if cost is not None else "")


def _group(number: int) -> str:
    return "{:,}".format(number).replace(",", " ")
