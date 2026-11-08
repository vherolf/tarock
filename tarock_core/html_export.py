"""Render a tournament's ranking.csv into a standalone results page.

No PyQt import, so it runs both from the desktop app and headless in GitHub
Actions (via scripts/export_html.py) to build docs/index.html for GitHub Pages.

Which tournament goes public is decided explicitly by tournaments/published.txt
(see `published_tournament`), never by "whatever is newest".
"""
from __future__ import annotations

import base64
import csv
import html
import io
from datetime import datetime
from pathlib import Path

import qrcode

from .paths import PUBLISHED_FILE, TOURNAMENTS_DIR, ordinal as _ordinal

PAGE_URL = "https://vherolf.github.io/tarock/"

_ROW_ACCENT = {1: "#FFD700", 2: "#C0C0C0", 3: "#CD7F32"}


def _qr_data_uri(url: str) -> str:
    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#FF0000", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"



def published_tournament(base: Path = TOURNAMENTS_DIR) -> Path:
    """Directory of the tournament chosen for publication in <base>/published.txt.

    The file holds a single tournament number. A missing or invalid file is an
    error on purpose: nothing is published by accident.
    """
    marker = base / PUBLISHED_FILE
    if not marker.exists():
        raise SystemExit(
            f"{marker} not found. Create it with the number of the tournament to publish, e.g. `16`."
        )
    text = marker.read_text(encoding="utf-8").strip()
    if not text.isdigit():
        raise SystemExit(f"{marker} must contain a tournament number, found {text!r}.")
    directory = base / str(int(text))
    if not (directory / "ranking.csv").exists():
        raise SystemExit(f"{marker} names tournament {text}, but {directory / 'ranking.csv'} does not exist.")
    return directory


def read_ranking(ranking_csv: Path) -> list[dict]:
    with open(ranking_csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return rows


def render_html(title: str, rows: list[dict], generated_at: datetime, page_url: str = PAGE_URL) -> str:
    body_rows = []
    for row in rows:
        rank = int(row["Rank"])
        name = html.escape(row["Player_Name"])
        points = row["Total_Points"]
        accent = _ROW_ACCENT.get(rank)
        row_style = f' style="background:{accent}22;"' if accent else ""
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, "")
        body_rows.append(
            f'        <tr{row_style}>'
            f'<td class="rank">{rank}{" " + medal if medal else ""}</td>'
            f'<td class="name">{name}</td>'
            f'<td class="points">{points}</td></tr>'
        )

    qr_uri = _qr_data_uri(page_url)

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
  .panels {{
    width: 100%;
    max-width: 900px;
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    align-items: flex-start;
    gap: 32px;
  }}
  .panel {{
    flex: 1 1 380px;
    max-width: 420px;
    display: flex;
    flex-direction: column;
    align-items: center;
  }}
  table {{
    width: 100%;
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
  .qr-card {{
    background: #fff;
    padding: 16px;
    border-radius: 12px;
    box-shadow: 0 8px 24px rgba(0,0,0,0.4);
  }}
  .qr-card img {{
    display: block;
    width: 220px;
    height: 220px;
  }}
  .qr-caption {{
    margin-top: 16px;
    color: #ccc;
    font-size: 14px;
    text-align: center;
  }}
  .qr-caption a {{
    color: #fff;
  }}
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
  <div class="panels">
    <div class="panel">
      <table>
        <thead>
          <tr><th>#</th><th>Player</th><th>Points</th></tr>
        </thead>
        <tbody>
{chr(10).join(body_rows)}
        </tbody>
      </table>
    </div>
    <div class="panel">
      <div class="qr-card">
        <img src="{qr_uri}" alt="QR code linking to this page">
      </div>
      <p class="qr-caption">Scan for the live results<br><a href="{html.escape(page_url)}">{html.escape(page_url)}</a></p>
    </div>
  </div>
  <footer>Generated {generated_at:%Y-%m-%d %H:%M}</footer>
</body>
</html>
"""


def build(tournament_dir: Path, out_path: Path, page_url: str = PAGE_URL) -> Path:
    ranking_csv = tournament_dir / "ranking.csv"
    rows = read_ranking(ranking_csv)
    num = int(tournament_dir.name) if tournament_dir.name.isdigit() else 0
    title = f"{_ordinal(num)} Pony Tarock Championship"
    generated_at = datetime.fromtimestamp(ranking_csv.stat().st_mtime)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_html(title, rows, generated_at, page_url), encoding="utf-8")
    return out_path
