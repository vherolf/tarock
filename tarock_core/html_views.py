"""HTML snippets for the data-entry tool's output box (pure functions, no Qt).

Kept out of the window class so the formatting - escaping, signs, colours, tie markers -
can be unit-tested.
"""
from __future__ import annotations

import html

from . import ranking
from .db import Game

NEGATIVE = "#b00020"
WINNER_TINT = "#FFF1B8"

# medal and row tint for ranks 1-3 (by rank, so tied players share them)
RANK_STYLE = {
    1: ("&#129351;", "#FFF1B8"),
    2: ("&#129352;", "#E8E8E8"),
    3: ("&#129353;", "#F3D9BF"),
}


def card_html(game: Game, number: int, total: int, names: dict[int, str]) -> str:
    """One table's result: names side by side on the first line, points below each name.

    Same column order as the entry fields; the player number sits in grey type, as large as the name, above it;
    the top scorer(s) get a tinted column.
    `number` / `total` position this game among all stored games ("entry 2 of 24").
    """
    top = max(points for _, points in game.seats)
    name_cells, point_cells = [], []
    for player, points in game.seats:
        bg = f' bgcolor="{WINNER_TINT}"' if points == top else ""
        color = NEGATIVE if points < 0 else "#000"
        name = html.escape(names.get(player, str(player)))
        name_cells.append(
            f'<td align="center" width="25%"{bg} style="padding:4px 8px; border-bottom:2px solid #999; white-space:nowrap;">'
            f'<span style="color:#999;">#{player}</span><br>'      # number above the name, same size as the name
            f"<b>{name}</b></td>"
        )
        point_cells.append(
            f'<td align="center"{bg} style="padding:6px 8px; font-size:xx-large; color:{color};">'
            f"<b>{points:+d}</b></td>"
        )
    return (
        f'<div style="margin:0 0 6px 0;"><span style="font-size:x-large; font-weight:bold;">'
        f"Round {game.round} &middot; Table {game.table}</span>"
        f' &nbsp;<span style="color:#888; font-size:small;">entry {number} of {total}</span></div>'
        f'<table width="100%" cellspacing="0">'
        f'<tr>{"".join(name_cells)}</tr><tr>{"".join(point_cells)}</tr></table>'
    )


def round_cell(cumulative: int, points: int | None, cell_style: str) -> str:
    """The round's own points (main number) + the running total in small light grey.

    points is None when the player sat out: a dash is shown, the total just carries over.
    """
    if points is None:
        main, color = "&ndash;", "#bbb"
    else:
        main, color = f"{points:+d}", (NEGATIVE if points < 0 else "#333")
    return (
        f'<td align="right" style="{cell_style} color:{color};">{main}'
        f'<br><span style="color:#b5b5b5; font-size:small;">{cumulative:+d}</span></td>'
    )


def ranking_html(standings: ranking.Standings) -> str:
    th = "padding:4px 10px; color:#666; font-weight:normal; border-bottom:2px solid #999;"
    head = (
        f'<tr><th align="left" style="{th}">Rank</th>'
        f'<th align="left" style="{th}">Player</th>'
        + "".join(f'<th align="right" style="{th}">R{r}</th>' for r in standings.rounds)
        + f'<th align="right" style="{th}">Total</th></tr>'
    )
    rows = []
    for s in standings.rows:
        medal, tint = RANK_STYLE.get(s.rank, ("", ""))
        bg = f' bgcolor="{tint}"' if tint else ""
        tie = '<span style="color:#888;">=</span>' if s.tied else ""
        cell = "padding:5px 10px; border-bottom:1px solid #ddd;"
        total_color = NEGATIVE if s.total < 0 else "#000"
        round_cells = "".join(
            round_cell(total, s.per_round.get(r), cell)
            for r, total in zip(standings.rounds, standings.cumulative(s.player))
        )
        rows.append(
            f"<tr{bg}>"
            f'<td style="{cell}"><b>{s.rank}</b>{tie} {medal}</td>'
            f'<td style="{cell}">'
            f'<span style="color:#999; font-size:small;">#{s.player}</span>'
            f" <b>{html.escape(s.name)}</b></td>"
            f"{round_cells}"
            f'<td align="right" style="{cell} color:{total_color};"><b>{s.total:+d}</b></td>'
            f"</tr>"
        )
    shared = " = marks a shared rank." if any(s.tied for s in standings.rows) else ""
    return (
        f'<h2 style="margin:0 0 6px 0;">Ranking</h2>'
        f'<table width="100%" cellspacing="0">{head}{"".join(rows)}</table>'
        f'<p style="color:#888; font-size:small;">Ties: most table wins, then best single round.{shared}</p>'
    )
