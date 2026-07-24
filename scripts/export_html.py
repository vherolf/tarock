#!/usr/bin/env python3
"""Render the latest tournament's ranking.csv into a standalone results page.

Standalone by design (no PyQt import) so it can run both from the desktop
app and headless in GitHub Actions to (re)build docs/index.html for
GitHub Pages.
"""
from __future__ import annotations

import argparse
import csv
import html
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOURNAMENTS_DIR = REPO_ROOT / "tournaments"

_ROW_ACCENT = {1: "#FFD700", 2: "#C0C0C0", 3: "#CD7F32"}


def _ordinal(n: int) -> str:
    suffix = "th" if 11 <= (n % 100) <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def find_latest_tournament(base: Path = TOURNAMENTS_DIR) -> Path | None:
    """Return the highest-numbered tournament dir that has a ranking.csv."""
    candidates = [
        d for d in base.iterdir()
        if d.is_dir() and d.name.isdigit() and (d / "ranking.csv").exists()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda d: int(d.name))


def read_ranking(ranking_csv: Path) -> list[dict]:
    with open(ranking_csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return rows


def render_html(title: str, rows: list[dict], generated_at: datetime) -> str:
    body_rows = []
    for row in rows:
        rank = int(row["Rank"])
        name = html.escape(row["Player_Name"])
        points = row["Total_Points"]
        accent = _ROW_ACCENT.get(rank)
        row_style = f' style="background:{accent}22;"' if accent else ""
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, "")
        body_rows.append(
            f'      <tr{row_style}>'
            f'<td class="rank">{rank}{" " + medal if medal else ""}</td>'
            f'<td class="name">{name}</td>'
            f'<td class="points">{points}</td></tr>'
        )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
  :root {{
    color-scheme: dark;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    min-height: 100vh;
    background: #0d0d1a;
    color: #fff;
    font-family: "Noto Serif", Georgia, serif;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 48px 16px 64px;
  }}
  h1 {{
    color: #FF0000;
    font-size: clamp(28px, 5vw, 44px);
    text-align: center;
    margin: 0 0 8px;
  }}
  .subtitle {{
    color: #ccc;
    font-size: 14px;
    margin-bottom: 32px;
    text-align: center;
  }}
  table {{
    width: 100%;
    max-width: 560px;
    border-collapse: collapse;
    background: #1a1a2e;
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 8px 24px rgba(0,0,0,0.4);
  }}
  thead th {{
    background: #FF0000;
    color: #fff;
    text-align: left;
    padding: 12px 20px;
    font-size: 15px;
    letter-spacing: 0.02em;
  }}
  tbody td {{
    padding: 12px 20px;
    border-top: 1px solid #2a2a40;
    font-size: 17px;
  }}
  td.rank {{ width: 64px; color: #ccc; font-variant-numeric: tabular-nums; }}
  td.points {{ text-align: right; font-weight: bold; font-variant-numeric: tabular-nums; }}
  th:last-child, td.points {{ text-align: right; }}
  footer {{
    margin-top: 32px;
    color: #666;
    font-size: 12px;
    text-align: center;
  }}
</style>
</head>
<body>
  <h1>{html.escape(title)}</h1>
  <p class="subtitle">Final ranking</p>
  <table>
    <thead>
      <tr><th>#</th><th>Player</th><th>Points</th></tr>
    </thead>
    <tbody>
{chr(10).join(body_rows)}
    </tbody>
  </table>
  <footer>Generated {generated_at:%Y-%m-%d %H:%M}</footer>
</body>
</html>
"""


def build(tournament_dir: Path, out_path: Path) -> Path:
    ranking_csv = tournament_dir / "ranking.csv"
    rows = read_ranking(ranking_csv)
    num = int(tournament_dir.name) if tournament_dir.name.isdigit() else 0
    title = f"{_ordinal(num)} Pony Tarock Championship"
    generated_at = datetime.fromtimestamp(ranking_csv.stat().st_mtime)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_html(title, rows, generated_at), encoding="utf-8")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tournament", type=int, default=None,
        help="Tournament number to export (default: latest with a ranking.csv)",
    )
    parser.add_argument(
        "--out", type=Path, default=REPO_ROOT / "docs" / "index.html",
        help="Output HTML path (default: docs/index.html)",
    )
    args = parser.parse_args()

    if args.tournament is not None:
        tournament_dir = TOURNAMENTS_DIR / str(args.tournament)
        if not (tournament_dir / "ranking.csv").exists():
            raise SystemExit(f"No ranking.csv found in {tournament_dir}")
    else:
        tournament_dir = find_latest_tournament()
        if tournament_dir is None:
            raise SystemExit("No tournament with a ranking.csv found under tournaments/")

    out_path = build(tournament_dir, args.out)
    print(f"Wrote {out_path} from {tournament_dir}")


if __name__ == "__main__":
    main()
