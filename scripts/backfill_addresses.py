"""Backfill trip_records start_address/end_address from stored coordinates.

Usage:
  python scripts/backfill_addresses.py --limit 100

This only updates rows whose address is empty or looks like raw "lat,lng".
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import DB_PATH  # noqa: E402
from utils.location_utils import format_location  # noqa: E402

COORD_RE = re.compile(r"^\s*-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?\s*$")


def needs_update(value) -> bool:
    if value is None:
        return True
    s = str(value).strip()
    return not s or s == "定位失败" or bool(COORD_RE.match(s))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id,start_lat,start_lng,start_address,end_lat,end_lng,end_address FROM trip_records ORDER BY id DESC LIMIT ?",
        (args.limit,),
    ).fetchall()

    updated = 0
    for row in rows:
        sets = []
        params = []
        if row["start_lat"] is not None and row["start_lng"] is not None and needs_update(row["start_address"]):
            addr = format_location(row["start_lat"], row["start_lng"])
            if addr and not COORD_RE.match(addr):
                sets.append("start_address=?")
                params.append(addr)
        if row["end_lat"] is not None and row["end_lng"] is not None and needs_update(row["end_address"]):
            addr = format_location(row["end_lat"], row["end_lng"])
            if addr and not COORD_RE.match(addr):
                sets.append("end_address=?")
                params.append(addr)
        if sets:
            params.append(row["id"])
            conn.execute(f"UPDATE trip_records SET {', '.join(sets)} WHERE id=?", params)
            updated += 1
    conn.commit()
    conn.close()
    print(f"Updated {updated} trip record(s).")


if __name__ == "__main__":
    main()
