#!/usr/bin/env python3
"""One-off import of legacy tournaments/<N>/*.csv into the SQLite database.

Validates every row and imports a tournament all-or-nothing; problems are
listed instead of being skipped silently.

    python scripts/import_csv.py            # all tournaments/<N> folders
    python scripts/import_csv.py 15 16      # only these
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tarock_core import csv_io, db, ranking  # noqa: E402
from tarock_core.paths import DEFAULT_DB, TOURNAMENTS_DIR  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("numbers", nargs="*", type=int, help="tournament numbers (default: all)")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--src", type=Path, default=TOURNAMENTS_DIR, help="folder holding <N>/ dirs")
    ap.add_argument("--compare", action="store_true",
                    help="also compare the imported ranking with the legacy ranking.csv")
    args = ap.parse_args()

    numbers = args.numbers or sorted(
        int(d.name) for d in args.src.iterdir()
        if d.is_dir() and d.name.isdigit() and (d / "result.csv").exists()
    )
    conn = db.open_rw(args.db)
    failed = False
    for n in numbers:
        if n in db.tournaments(conn):
            print(f"tournament {n}: already in database, skipped")
            continue
        try:
            count = csv_io.import_tournament(conn, n, args.src / str(n))
        except csv_io.ImportErrors as exc:
            failed = True
            print(f"tournament {n}: NOT imported, {len(exc.errors)} problem(s):")
            for e in exc.errors:
                print(f"   - {e}")
            continue
        problems = db.check(conn, n)
        print(f"tournament {n}: imported {count} games" + (f", AUDIT: {problems}" if problems else ""))
        if args.compare:
            _compare(conn, n, args.src / str(n))
    return 1 if failed else 0


def _compare(conn, n: int, src: Path) -> None:
    import csv
    new = ranking.compute(db.games(conn, n), db.players(conn, n))
    with open(src / "ranking.csv", newline="", encoding="utf-8") as f:
        old = list(csv.DictReader(f))
    old_totals = {int(r["Player_Number"]): int(r["Total_Points"]) for r in old}
    new_totals = {s.player: s.total for s in new.rows}
    print("   totals match legacy ranking.csv" if old_totals == new_totals
          else f"   TOTALS DIFFER from legacy ranking.csv: {old_totals} vs {new_totals}")
    old_order = [int(r["Player_Number"]) for r in old]
    new_order = [s.player for s in new.rows]
    if old_order != new_order:
        print(f"   order differs (tie-break rules changed): legacy {old_order} -> new {new_order}")
    for s in new.rows:
        if s.tied:
            print(f"   still tied after tie-breaks: rank {s.rank} {s.name} ({s.total})")


if __name__ == "__main__":
    sys.exit(main())
