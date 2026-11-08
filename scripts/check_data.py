#!/usr/bin/env python3
"""Verify the committed tournament CSVs are consistent (used by CI before publishing).

Exit code 0 = all good, 1 = problems found.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tarock_core import consistency  # noqa: E402
from tarock_core.paths import TOURNAMENTS_DIR  # noqa: E402


def main() -> int:
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else TOURNAMENTS_DIR
    failed = False
    for label, problems in consistency.check_all(base).items():
        if problems:
            failed = True
            print(f"FAIL {label}")
            for p in problems:
                print(f"     {p}")
        else:
            print(f"ok   {label}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
