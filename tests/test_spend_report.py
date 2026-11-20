"""The spend report adds up spend per person, month and model, and ignores top-ups."""

import csv
import json

from spend_report import build_report, main, per_person

USERS = [
    {"_id": {"$oid": "u1"}, "email": "ana@example-company.com"},
    {"_id": {"$oid": "u2"}, "email": "ben@example-company.com"},
]
TRANSACTIONS = [
    # mongoexport relaxed format
    {"user": {"$oid": "u1"}, "model": "gpt-6-luna", "tokenType": "prompt",
     "rawAmount": -1200, "tokenValue": -3600, "createdAt": {"$date": "2026-11-03T10:00:00Z"}},
    {"user": {"$oid": "u1"}, "model": "gpt-6-luna", "tokenType": "completion",
     "rawAmount": -300, "tokenValue": -4500, "createdAt": {"$date": "2026-11-03T10:00:01Z"}},
    # canonical format (dates as milliseconds, numbers as strings)
    {"user": {"$oid": "u2"}, "model": "grok-4.7", "tokenType": "prompt",
     "rawAmount": {"$numberInt": "-2000"}, "tokenValue": {"$numberDouble": "-500000"},
     "createdAt": {"$date": {"$numberLong": "1794477600000"}}},
    # a monthly refill: positive, so not spend
    {"user": {"$oid": "u2"}, "tokenType": "credits", "rawAmount": 20000000, "tokenValue": 20000000,
     "createdAt": {"$date": "2026-11-01T00:00:00Z"}},
    # another month
    {"user": {"$oid": "u1"}, "model": "gpt-6-sol", "tokenType": "prompt",
     "rawAmount": -100, "tokenValue": -250, "createdAt": {"$date": "2026-10-30T12:00:00Z"}},
]


def test_spend_is_grouped_by_month_person_and_model():
    rows = build_report(USERS, TRANSACTIONS, month="2026-11")
    assert rows == [
        {"month": "2026-11", "user_email": "ana@example-company.com", "model": "gpt-6-luna",
         "input_tokens": 1200, "output_tokens": 300, "credits": 8100, "usd": 0.0081},
        {"month": "2026-11", "user_email": "ben@example-company.com", "model": "grok-4.7",
         "input_tokens": 2000, "output_tokens": 0, "credits": 500000, "usd": 0.5},
    ]


def test_refills_are_not_counted_as_spend():
    rows = build_report(USERS, TRANSACTIONS)
    assert all(row["model"] != "unknown model" for row in rows)


def test_unknown_users_are_kept_visible():
    rows = build_report([], TRANSACTIONS[:1])
    assert rows[0]["user_email"] == "unknown user"


def test_totals_per_person_are_sorted_by_spend():
    rows = build_report(USERS, TRANSACTIONS, month="2026-11")
    assert [email for email, _ in per_person(rows)] == ["ben@example-company.com", "ana@example-company.com"]


def test_command_line_writes_a_csv(tmp_path, capsys):
    users = tmp_path / "users.jsonl"
    txs = tmp_path / "transactions.jsonl"
    out = tmp_path / "spend.csv"
    users.write_text("\n".join(json.dumps(u) for u in USERS) + "\n")
    txs.write_text("\n".join(json.dumps(t) for t in TRANSACTIONS) + "\n")
    assert main(["--users", str(users), "--transactions", str(txs), "--month", "2026-11", "--out", str(out)]) == 0
    with out.open() as fh:
        assert len(list(csv.DictReader(fh))) == 2
    assert "ben@example-company.com" in capsys.readouterr().out
