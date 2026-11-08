"""Display data for the presentation, derived from the standings - pure, no Qt."""
from __future__ import annotations

from dataclasses import dataclass

from tarock_core import ranking

# 24 colours, readable on the dark background. The first 14 are the original palette (existing
# players keep their look); the rest were chosen as the colours farthest (CIE Lab distance) from
# everything already in the palette. tests/test_viewmodel.py guards uniqueness and readability.
PLAYER_COLORS = (
    "gold", "silver", "#CD7F32", "steelblue", "tomato", "limegreen",
    "orchid", "cyan", "orange", "hotpink", "yellowgreen", "aquamarine",
    "cornflowerblue", "salmon",
    "#FF00FF", "#F0E68C", "#00FA9A", "#00FF00", "#3CB371",
    "#FFB6C1", "#20B2AA", "#87CEFA", "#DDA0DD", "#FAFAD2",
)


@dataclass(frozen=True)
class PlayerView:
    pnum: str            # player number as text (stable widget/dict key)
    rank: int
    name: str
    total: int
    color: str
    cumulative: tuple[int, ...]   # running total after each round


@dataclass(frozen=True)
class View:
    rounds: tuple[int, ...]
    players: tuple[PlayerView, ...]   # in ranking order


def assign_colors(order: list[str], previous: dict[str, str] | None = None) -> dict[str, str]:
    """A colour per player. Players seen before keep theirs; new players get an unused one.

    The palette is finite: with more players than colours, colours repeat.
    """
    colors = {p: c for p, c in (previous or {}).items() if p in order}
    free = [c for c in PLAYER_COLORS if c not in colors.values()]
    for pnum in order:
        if pnum not in colors:
            colors[pnum] = free.pop(0) if free else PLAYER_COLORS[len(colors) % len(PLAYER_COLORS)]
    return colors


def build_view(standings: ranking.Standings, previous_colors: dict[str, str] | None = None) -> View:
    order = [str(s.player) for s in standings.rows]
    colors = assign_colors(order, previous_colors)
    players = tuple(
        PlayerView(
            pnum=str(s.player),
            rank=s.rank,
            name=s.name,
            total=s.total,
            color=colors[str(s.player)],
            cumulative=tuple(standings.cumulative(s.player)),
        )
        for s in standings.rows
    )
    return View(rounds=tuple(standings.rounds), players=players)
