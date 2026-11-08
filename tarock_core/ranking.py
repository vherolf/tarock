"""Ranking logic - the single place where standings are computed.

Pure functions, no I/O. Used by the data-entry tool, the presentation tool
and the CSV/HTML export so they can never disagree.

Rules
-----
1. Total points (higher is better).
2. Tie-break 1: number of table wins. A win is the highest score at a table
   in a round; if several players share the top score at a table, each of
   them gets the win.
3. Tie-break 2: best single-round score.
4. Still equal -> shared rank (competition ranking: 1, 2, 2, 4).
   Players with a shared rank are listed by name, then number, for display.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .db import Game


@dataclass(frozen=True)
class Standing:
    rank: int
    player: int
    name: str
    total: int
    wins: int
    best_round: int
    per_round: dict[int, int] = field(default_factory=dict)  # round -> points
    tied: bool = False  # shares its rank with at least one other player


@dataclass(frozen=True)
class Standings:
    rounds: list[int]
    rows: list[Standing]

    def cumulative(self, player: int) -> list[int]:
        """Cumulative total after each round in `rounds` (flat if not played)."""
        row = next(s for s in self.rows if s.player == player)
        total, out = 0, []
        for r in self.rounds:
            total += row.per_round.get(r, 0)
            out.append(total)
        return out


def compute(games: list[Game], names: dict[int, str]) -> Standings:
    per_round: dict[int, dict[int, int]] = {}
    wins: dict[int, int] = {}
    for game in games:
        top = max(points for _, points in game.seats)
        for player, points in game.seats:
            bucket = per_round.setdefault(player, {})
            bucket[game.round] = bucket.get(game.round, 0) + points
            wins.setdefault(player, 0)
            if points == top:
                wins[player] += 1

    def key(p: int) -> tuple:
        return (-sum(per_round[p].values()), -wins[p], -max(per_round[p].values()))

    order = sorted(per_round, key=lambda p: (key(p), names.get(p, "").casefold(), p))

    rows: list[Standing] = []
    for i, p in enumerate(order):
        rank = 1 + sum(1 for q in order if key(q) < key(p))
        tied = sum(1 for q in order if key(q) == key(p)) > 1
        rows.append(Standing(
            rank=rank,
            player=p,
            name=names.get(p, str(p)),
            total=sum(per_round[p].values()),
            wins=wins[p],
            best_round=max(per_round[p].values()),
            per_round=dict(per_round[p]),
            tied=tied,
        ))
    return Standings(rounds=sorted({g.round for g in games}), rows=rows)
