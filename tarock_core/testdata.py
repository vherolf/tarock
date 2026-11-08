"""Throw-away test tournaments, regenerated at every start of the data-entry tool.

Tournament 0 has 14 players (3 tables, 2 players sit out each round) and tournament 1 has 16 players
(4 tables). They are generated fresh each time - so whatever was deleted or changed while testing is gone
at the next start - and are meant for trying the tools out; they are gitignored.

The data goes through the normal path: the CSV files are written first (the master copy), then the
database follows them (see sync.py). No backup is made of what is replaced: it is test data.
"""
from __future__ import annotations

import random
from pathlib import Path

from . import csv_io, db, sync

TEST_TOURNAMENTS = ((0, 14), (1, 16))      # (tournament number, players)
ROUNDS = 6

FIRST_NAMES = [
    "Hans", "Greta", "Franz", "Resi", "Sepp", "Liesl", "Karl", "Maria", "Toni", "Burgi",
    "Rudi", "Vroni", "Peppi", "Lotte", "Gustl", "Hilde", "Fritz", "Anni", "Poldi", "Mizzi",
]


def generate(n_players: int, rounds: int, rng: random.Random) -> csv_io.ParsedTournament:
    """Players and games of a made-up tournament that obeys every rule of the database.

    Per round, `n_players // 4` tables of four play; the remaining players sit out, rotating so that
    nobody sits out twice before everyone has sat out once. Every table's points sum to 0.
    """
    if not 4 <= n_players <= len(FIRST_NAMES):
        raise ValueError(f"n_players must be between 4 and {len(FIRST_NAMES)}")
    names = FIRST_NAMES[:]
    rng.shuffle(names)
    players = {i + 1: names[i] for i in range(n_players)}
    tables = n_players // 4
    sat_out = {p: 0 for p in players}
    games: list[csv_io.ParsedGame] = []
    for rnd in range(1, rounds + 1):
        resting = sorted(players, key=lambda p: (sat_out[p], rng.random()))[: n_players - tables * 4]
        for p in resting:
            sat_out[p] += 1
        playing = [p for p in players if p not in resting]
        rng.shuffle(playing)
        for table in range(tables):
            seated = playing[table * 4:(table + 1) * 4]
            while True:                                   # three random scores, the fourth balances them
                points = [rng.randint(-26, 26) for _ in range(3)]
                if abs(sum(points)) <= 40:
                    break
            points.append(-sum(points))
            rng.shuffle(points)
            games.append(csv_io.ParsedGame(len(games) + 2, rnd, table + 1, tuple(zip(seated, points))))
    return csv_io.ParsedTournament(players, tuple(games))


def refresh(db_path: Path, seed: int | None = None) -> int:
    """(Re)create the test tournaments next to `db_path`, replacing whatever is there. Returns the seed used.

    Tournament k uses seed + k, so one number reproduces both. Other tournaments are not touched.
    """
    if seed is None:
        seed = random.SystemRandom().randrange(1_000_000)
    conn = db.open_rw(db_path)
    try:
        for offset, (number, n_players) in enumerate(TEST_TOURNAMENTS):
            csv_dir = db_path.parent / str(number)
            csv_io.write_parsed(generate(n_players, ROUNDS, random.Random(seed + offset)), csv_dir)
            result = sync.sync_tournament(conn, number, csv_dir, backup_dir=None)
            if result.action == "invalid":
                raise RuntimeError(f"generated test tournament {number} is invalid: {result.errors}")
    finally:
        conn.close()
    return seed
