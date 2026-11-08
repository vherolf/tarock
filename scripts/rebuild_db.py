#!/usr/bin/env python3
"""Make the SQLite database match the CSV files in tournaments/<N>/ (the CSV files are the master copy).

    python scripts/rebuild_db.py              # all tournaments that have CSV files
    python scripts/rebuild_db.py 15 16        # only these
    python scripts/rebuild_db.py --dry-run    # just report what would change

Use it after deleting the database, after a git clone/pull, or to check consistency. A tournament whose
database content differs is replaced by its CSV files - after the whole database was saved to
tournaments/backups/. Invalid CSV files are reported and change nothing.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tarock_core import db, sync  # noqa: E402
from tarock_core.paths import DEFAULT_DB  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("numbers", nargs="*", type=int, help="tournament numbers (default: all with CSV files)")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--src", type=Path, default=None, help="folder holding the <N>/ CSV folders (default: next to the database)")
    ap.add_argument("--dry-run", action="store_true", help="report only, change nothing")
    args = ap.parse_args()

    src = args.src or args.db.parent
    numbers = args.numbers or sync.csv_tournament_numbers(src)
    if not numbers:
        print(f"no tournament CSV folders found in {src}")
        return 0

    conn = db.open_rw(args.db) if not args.dry_run else db.open_ro(args.db) if args.db.exists() else db.open_rw(Path(":memory:"))
    failed = False
    for n in numbers:
        csv_dir = src / str(n)
        if args.dry_run:
            status, errors = sync.check(conn, n, csv_dir)
            label = {"in_sync": "in sync", "differs": "WOULD BE REBUILT from the CSV files",
                     "no_csv": "no CSV files", "invalid": "INVALID CSV files"}[status]
            print(f"tournament {n}: {label}")
            failed |= status == "invalid"
            for e in errors:
                print(f"   - {e}")
            continue
        result = sync.sync_tournament(conn, n, csv_dir, backup_dir=args.db.parent / "backups")
        if result.action == "invalid":
            failed = True
            print(f"tournament {n}: NOT changed - the CSV files have {len(result.errors)} problem(s):")
            for e in result.errors:
                print(f"   - {e}")
            continue
        line = {"in_sync": "already in sync", "rebuilt": f"rebuilt from the CSV files ({result.games} games)",
                "exported": "CSV files created from the database", "nothing": "nothing to do"}[result.action]
        if result.replaced_data:
            line += f" - the old database content was saved to {result.backup}"
        if result.ranking_refreshed:
            line += " - ranking.csv regenerated"
        for w in result.warnings:
            line += f"\n   WARNING: {w}"
        print(f"tournament {n}: {line}")
        problems = db.check(conn, n)
        if problems:
            failed = True
            print(f"   AUDIT: {problems}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
