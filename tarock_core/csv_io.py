"""CSV import (legacy data) and export (text copy committed to git for the website)."""
from __future__ import annotations

import csv
import os
import sqlite3
import tempfile
from pathlib import Path

from . import db, ranking


class ImportErrors(Exception):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("\n".join(errors))
        self.errors = errors


def _atomic_write(path: Path, rows: list[list]) -> None:
    """Write a CSV so readers never see a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(rows)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def export_tournament(conn: sqlite3.Connection, tournament: int, out_dir: Path) -> None:
    """Write result.csv, player_numbers.csv and ranking.csv derived from the database."""
    names = db.players(conn, tournament)
    games = db.games(conn, tournament)

    result = [["Table", "Round"] + [c for i in range(1, 5) for c in (f"Player_Number{i}", f"Points{i}")]]
    for g in games:
        result.append([g.table, g.round] + [v for seat in g.seats for v in seat])
    _atomic_write(out_dir / "result.csv", result)

    _atomic_write(
        out_dir / "player_numbers.csv",
        [["Player_Number", "Player_Name"]] + [[n, name] for n, name in sorted(names.items())],
    )

    standings = ranking.compute(games, names)
    _atomic_write(
        out_dir / "ranking.csv",
        [["Rank", "Player_Number", "Player_Name", "Total_Points"]]
        + [[s.rank, s.player, s.name, s.total] for s in standings.rows],
    )


def import_tournament(conn: sqlite3.Connection, tournament: int, src_dir: Path) -> int:
    """Import player_numbers.csv + result.csv. All-or-nothing; returns the number of games.

    Raises ImportErrors listing *every* problem found, so bad rows are never silently dropped.
    """
    errors: list[str] = []
    mapping: dict[int, str] = {}
    map_file = src_dir / "player_numbers.csv"
    with open(map_file, newline="", encoding="utf-8") as f:
        for ln, row in enumerate(list(csv.reader(f))[1:], start=2):
            if not row:
                continue
            try:
                mapping[int(row[0])] = row[1].strip()
            except (ValueError, IndexError):
                errors.append(f"{map_file.name} line {ln}: unreadable row {row!r}")

    parsed: list[tuple[int, int, list[tuple[int, int]], int]] = []
    res_file = src_dir / "result.csv"
    with open(res_file, newline="", encoding="utf-8") as f:
        for ln, row in enumerate(list(csv.reader(f))[1:], start=2):
            if not row:
                continue
            try:
                seats = [(int(row[2 + 2 * i]), int(row[3 + 2 * i])) for i in range(4)]
                parsed.append((int(row[1]), int(row[0]), seats, ln))
            except (ValueError, IndexError):
                errors.append(f"{res_file.name} line {ln}: unreadable row {row!r}")
    if errors:
        raise ImportErrors(errors)

    # Validate everything in a transaction we always roll back on any problem.
    try:
        conn.execute("BEGIN")
        conn.execute("INSERT OR IGNORE INTO tournament(number) VALUES (?)", (tournament,))
        try:
            _insert_players(conn, tournament, mapping)
        except db.ValidationError as exc:
            errors.append(f"{map_file.name}: {exc}")
        for round_, table, seats, ln in parsed:
            try:
                db.validate_game(conn, tournament, round_, table, seats)
                cur = conn.execute(
                    "INSERT INTO game(tournament, round, table_no) VALUES (?,?,?)",
                    (tournament, round_, table),
                )
                conn.executemany(
                    "INSERT INTO result(game_id, tournament, round, seat, player, points) "
                    "VALUES (?,?,?,?,?,?)",
                    [(cur.lastrowid, tournament, round_, i + 1, p, pts) for i, (p, pts) in enumerate(seats)],
                )
            except (db.ValidationError, sqlite3.IntegrityError) as exc:
                errors.append(f"{res_file.name} line {ln} (round {round_}, table {table}): {exc}")
        if errors:
            raise ImportErrors(errors)
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    return len(parsed)


def _insert_players(conn: sqlite3.Connection, tournament: int, mapping: dict[int, str]) -> None:
    folded = [n.casefold() for n in mapping.values()]
    if any(not n for n in folded) or len(set(folded)) != len(folded):
        raise db.ValidationError("player names must be non-empty and unique")
    conn.executemany(
        "INSERT INTO player(tournament, number, name) VALUES (?,?,?)",
        [(tournament, n, name) for n, name in mapping.items()],
    )
