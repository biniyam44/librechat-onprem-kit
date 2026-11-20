#!/usr/bin/env python3
"""Monthly AI spend per person and model, from LibreChat's transaction records.

LibreChat writes one transaction per model call (prompt and completion) and stores
the cost as token credits. This script turns an export of those records into a CSV
for finance and a short summary for IT. It needs only the Python standard library.

On the LibreChat server:
  C="docker compose -f deploy-compose.yml -f compose.onprem.yml exec -T mongodb"
  $C mongoexport --quiet -d LibreChat -c users --fields _id,email > users.jsonl
  $C mongoexport --quiet -d LibreChat -c transactions > transactions.jsonl
  python3 scripts/spend_report.py --users users.jsonl --transactions transactions.jsonl \
      --month 2026-11 --out spend-2026-11.csv

Credits are converted with --credits-per-usd (default 1,000,000, LibreChat's
documented rate). Confirm the rate and the model prices for your LibreChat version.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

CREDITS_PER_USD = 1_000_000
FIELDS = ["month", "user_email", "model", "input_tokens", "output_tokens", "credits", "usd"]


def _plain(value: Any) -> Any:
    """Unwrap mongoexport's Extended JSON ({"$oid": ...}, {"$date": ...}, {"$numberLong": ...})."""
    if isinstance(value, dict) and len(value) == 1:
        key, inner = next(iter(value.items()))
        if key in ("$oid", "$numberLong", "$numberInt", "$numberDouble", "$numberDecimal"):
            return inner if key == "$oid" else float(inner)
        if key == "$date":
            return _plain(inner) if isinstance(inner, dict) else inner
    return value


def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        for number, line in enumerate(fh, start=1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise SystemExit(f"{path}:{number}: not valid JSON ({exc.msg})") from exc


def month_of(created: Any) -> str:
    created = _plain(created)
    if isinstance(created, (int, float)):  # canonical $date: milliseconds since epoch
        from datetime import datetime, timezone

        return datetime.fromtimestamp(created / 1000, tz=timezone.utc).strftime("%Y-%m")
    return str(created)[:7]


@dataclass
class Row:
    input_tokens: int = 0
    output_tokens: int = 0
    credits: float = 0.0


def build_report(
    users: Iterable[dict[str, Any]],
    transactions: Iterable[dict[str, Any]],
    month: str | None = None,
    credits_per_usd: float = CREDITS_PER_USD,
) -> list[dict[str, Any]]:
    emails = {str(_plain(u.get("_id"))): u.get("email") or "unknown" for u in users}
    totals: dict[tuple[str, str, str], Row] = defaultdict(Row)
    for tx in transactions:
        value = float(_plain(tx.get("tokenValue")) or 0)
        if value >= 0:
            continue  # positive values are top-ups and refills, not spend
        tx_month = month_of(tx.get("createdAt"))
        if month and tx_month != month:
            continue
        email = emails.get(str(_plain(tx.get("user"))), "unknown user")
        row = totals[(tx_month, email, tx.get("model") or "unknown model")]
        tokens = int(abs(float(_plain(tx.get("rawAmount")) or 0)))
        if tx.get("tokenType") == "completion":
            row.output_tokens += tokens
        else:
            row.input_tokens += tokens
        row.credits += abs(value)
    return [
        {
            "month": m,
            "user_email": e,
            "model": model,
            "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens,
            "credits": round(r.credits),
            "usd": round(r.credits / credits_per_usd, 4),
        }
        for (m, e, model), r in sorted(totals.items())
    ]


def per_person(rows: list[dict[str, Any]]) -> list[tuple[str, float]]:
    spend: dict[str, float] = defaultdict(float)
    for row in rows:
        spend[row["user_email"]] += row["usd"]
    return sorted(spend.items(), key=lambda item: item[1], reverse=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--users", type=Path, required=True)
    parser.add_argument("--transactions", type=Path, required=True)
    parser.add_argument("--month", help="only this month, as YYYY-MM")
    parser.add_argument("--credits-per-usd", type=float, default=CREDITS_PER_USD)
    parser.add_argument("--out", type=Path, help="CSV file to write (default: stdout)")
    args = parser.parse_args(argv)

    rows = build_report(read_jsonl(args.users), read_jsonl(args.transactions), args.month, args.credits_per_usd)
    out = args.out.open("w", newline="", encoding="utf-8") if args.out else sys.stdout
    writer = csv.DictWriter(out, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    if args.out:
        out.close()
        print(f"wrote {len(rows)} rows to {args.out}")
        for email, usd in per_person(rows):
            print(f"  {email:<40} ${usd:,.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
