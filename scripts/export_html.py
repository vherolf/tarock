#!/usr/bin/env python3
"""Build the public results page (docs/index.html) for GitHub Pages.

By default the tournament named in tournaments/published.txt is rendered, so
nothing becomes public by accident. Use --tournament N to render another one
(e.g. for a local preview).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tarock_core import html_export  # noqa: E402
from tarock_core.paths import DATA_ROOT, TOURNAMENTS_DIR  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument(
        "--tournament", type=int, default=None,
        help="Tournament number to render (default: the one in tournaments/published.txt)",
    )
    parser.add_argument(
        "--out", type=Path, default=DATA_ROOT / "docs" / "index.html",
        help="Output HTML path (default: docs/index.html)",
    )
    parser.add_argument(
        "--url", default=html_export.PAGE_URL,
        help=f"URL to encode in the QR code (default: {html_export.PAGE_URL})",
    )
    args = parser.parse_args()

    if args.tournament is not None:
        tournament_dir = TOURNAMENTS_DIR / str(args.tournament)
        if not (tournament_dir / "ranking.csv").exists():
            raise SystemExit(f"No ranking.csv found in {tournament_dir}")
    else:
        tournament_dir = html_export.published_tournament()

    out_path = html_export.build(tournament_dir, args.out, args.url)
    print(f"Wrote {out_path} from {tournament_dir}")


if __name__ == "__main__":
    main()
