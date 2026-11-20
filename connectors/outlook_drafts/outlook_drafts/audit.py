"""Append-only, hash-chained audit log in JSON Lines.

Every record stores the hash of the record before it. Editing, removing or
reordering a past line breaks the chain, and `verify()` reports the first bad
line. One line per action keeps the file easy to ship to a SIEM or to read
during a go-live review.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GENESIS = "0" * 64


def _digest(record: dict[str, Any]) -> str:
    body = {k: v for k, v in record.items() if k != "hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AuditLog:
    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._last_hash = self._read_last_hash()

    def _read_last_hash(self) -> str:
        if not self.path.exists():
            return GENESIS
        last = GENESIS
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    last = json.loads(line)["hash"]
        return last

    def append(self, **fields: Any) -> dict[str, Any]:
        with self._lock:
            record: dict[str, Any] = {
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                **fields,
                "prev": self._last_hash,
            }
            record["hash"] = _digest(record)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            self._last_hash = record["hash"]
            return record

    def records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def verify(self) -> tuple[bool, int | None]:
        """Return (True, None) if the chain is intact, else (False, first bad line number)."""
        prev = GENESIS
        for number, record in enumerate(self.records(), start=1):
            if record.get("prev") != prev or record.get("hash") != _digest(record):
                return False, number
            prev = record["hash"]
        return True, None


if __name__ == "__main__":  # python -m outlook_drafts.audit /audit/outlook-actions.jsonl
    import sys

    ok, line = AuditLog(sys.argv[1]).verify()
    print("audit log intact" if ok else f"audit log broken at line {line}")
    sys.exit(0 if ok else 1)
