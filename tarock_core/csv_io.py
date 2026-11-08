"""CSV files <-> database.

The CSV files in tournaments/<N>/ are the durable record of a tournament (committed to git,
readable, mergeable between machines); the SQLite database is a working copy that can always be
rebuilt from them (see sync.py). This module reads and writes that file format:

    result.csv          one row per table and round
    player_numbers.csv  player number -> name
    ranking.csv         derived standings (never read back as data, always recomputed)
"""
from __future__ import annotations

import csv
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import db, ranking

RESULT_FILE = "result.csv"
PLAYERS_FILE = "player_numbers.csv"
RANKING_FILE = "ranking.csv"

_RESULT_HEADER = ["Table", "Round"] + [c for i in range(1, 5) for c in (f"Player_Number{i}", f"Points{i}")]
_PLAYERS_HEADER = ["Player_Number", "Player_Name"]
_RANKING_HEADER = ["Rank", "Player_Number", "Player_Name", "Total_Points"]


class ImportErrors(Exception):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("\n".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class ParsedGame:
    line: int                              # line number in result.csv, for error messages
    round: int
    table: int
    seats: tuple[tuple[int, int], ...]     # ((player, points) x 4)


@dataclass(frozen=True)
class ParsedTournament:
    players: dict[int, str]
    games: tuple[ParsedGame, ...]          # in file order


# ------------------------------------------------------------------ writing ----
def _write_temp(path: Path, rows: list[list]) -> Path:
    """Write rows to a temp file next to `path` (not visible under its final name yet)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(rows)
    except BaseException:
        os.unlink(tmp)
        raise
    return Path(tmp)


def _write_all(files: dict[Path, list[list]]) -> None:
    """All-or-nothing: every file is written to a temp file first; only then are they moved into place.

    If any write fails (disk full, read-only folder) nothing is replaced and no temp files are left.
    """
    temps: list[tuple[Path, Path]] = []
    try:
        for path, rows in files.items():
            temps.append((_write_temp(path, rows), path))
    except BaseException:
        for tmp, _ in temps:
            tmp.unlink(missing_ok=True)
        raise
    for tmp, path in temps:
        os.replace(tmp, path)


def _result_rows(games: list[db.Game]) -> list[list]:
    return [_RESULT_HEADER] + [[g.table, g.round] + [v for seat in g.seats for v in seat] for g in games]


def _players_rows(names: dict[int, str]) -> list[list]:
    return [_PLAYERS_HEADER] + [[n, name] for n, name in sorted(names.items())]


def ranking_rows(standings: ranking.Standings) -> list[list]:
    return [_RANKING_HEADER] + [[s.rank, s.player, s.name, s.total] for s in standings.rows]


def export_tournament(conn: sqlite3.Connection, tournament: int, out_dir: Path) -> None:
    """Write result.csv, player_numbers.csv and ranking.csv from the database, all-or-nothing."""
    names = db.players(conn, tournament)
    games = db.games(conn, tournament)
    _write_all({
        out_dir / RESULT_FILE: _result_rows(games),
        out_dir / PLAYERS_FILE: _players_rows(names),
        out_dir / RANKING_FILE: ranking_rows(ranking.compute(games, names)),
    })


def write_parsed(parsed: ParsedTournament, out_dir: Path) -> None:
    """Write a tournament that exists only in memory (e.g. generated test data) as its three CSV files, all-or-nothing."""
    games = [db.Game(i + 1, g.round, g.table, g.seats) for i, g in enumerate(parsed.games)]
    _write_all({
        out_dir / RESULT_FILE: _result_rows(games),
        out_dir / PLAYERS_FILE: _players_rows(parsed.players),
        out_dir / RANKING_FILE: ranking_rows(ranking.compute(games, parsed.players)),
    })


def export_ranking(conn: sqlite3.Connection, tournament: int, out_dir: Path) -> None:
    """Rewrite only the derived ranking.csv (the data files stay untouched)."""
    standings = ranking.compute(db.games(conn, tournament), db.players(conn, tournament))
    _write_all({out_dir / RANKING_FILE: ranking_rows(standings)})


# ------------------------------------------------------------------ reading ----
def parse_tournament(src_dir: Path) -> ParsedTournament:
    """Read player_numbers.csv + result.csv strictly. Raises ImportErrors listing *every* unreadable row."""
    errors: list[str] = []
    players: dict[int, str] = {}
    games: list[ParsedGame] = []

    def rows_of(name: str) -> list[list[str]] | None:
        path = src_dir / name
        if not path.exists():
            errors.append(f"{name} is missing")
            return None
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.reader(f))[1:]            # skip the header

    for ln, row in enumerate(rows_of(PLAYERS_FILE) or [], start=2):
        if not row:
            continue
        try:
            players[int(row[0])] = row[1].strip()
        except (ValueError, IndexError):
            errors.append(f"{PLAYERS_FILE} line {ln}: unreadable row {row!r}")

    for ln, row in enumerate(rows_of(RESULT_FILE) or [], start=2):
        if not row:
            continue
        try:
            seats = tuple((int(row[2 + 2 * i]), int(row[3 + 2 * i])) for i in range(4))
            games.append(ParsedGame(ln, int(row[1]), int(row[0]), seats))
        except (ValueError, IndexError):
            errors.append(f"{RESULT_FILE} line {ln}: unreadable row {row!r}")

    if errors:
        raise ImportErrors(errors)
    return ParsedTournament(players, tuple(games))


def load_tournament(conn: sqlite3.Connection, tournament: int, parsed: ParsedTournament, *, replace: bool = False) -> int:
    """Store parsed CSV data in the database, all-or-nothing; returns the number of games.

    replace=True first removes the tournament's existing data inside the same transaction, so
    a rejected file leaves the old data untouched. Every rule of the schema is checked; raises
    ImportErrors listing every problem.
    """
    errors: list[str] = []
    with db.transaction(conn):
        conn.execute("INSERT OR IGNORE INTO tournament(number) VALUES (?)", (tournament,))
        if replace:
            for table in ("result", "game", "player"):      # children first (results reference players)
                conn.execute(f"DELETE FROM {table} WHERE tournament = ?", (tournament,))
        try:
            _insert_players(conn, tournament, parsed.players)
        except (db.ValidationError, sqlite3.IntegrityError) as exc:
            errors.append(f"{PLAYERS_FILE}: {exc}")
        for game in parsed.games:
            try:
                db.validate_game(conn, tournament, game.round, game.table, list(game.seats))
                cur = conn.execute(
                    "INSERT INTO game(tournament, round, table_no) VALUES (?,?,?)",
                    (tournament, game.round, game.table),
                )
                conn.executemany(
                    "INSERT INTO result(game_id, tournament, round, seat, player, points) VALUES (?,?,?,?,?,?)",
                    [(cur.lastrowid, tournament, game.round, i + 1, p, pts) for i, (p, pts) in enumerate(game.seats)],
                )
            except (db.ValidationError, sqlite3.IntegrityError) as exc:
                errors.append(f"{RESULT_FILE} line {game.line} (round {game.round}, table {game.table}): {exc}")
        if errors:
            raise ImportErrors(errors)       # rolls the whole transaction back
    return len(parsed.games)


def import_tournament(conn: sqlite3.Connection, tournament: int, src_dir: Path) -> int:
    """Read a tournament folder into a database that does not have it yet. Returns the number of games."""
    return load_tournament(conn, tournament, parse_tournament(src_dir))


def _insert_players(conn: sqlite3.Connection, tournament: int, mapping: dict[int, str]) -> None:
    folded = [n.casefold() for n in mapping.values()]
    if any(not n for n in folded) or len(set(folded)) != len(folded):
        raise db.ValidationError("player names must be non-empty and unique")
    conn.executemany(
        "INSERT INTO player(tournament, number, name) VALUES (?,?,?)",
        [(tournament, n, name) for n, name in mapping.items()],
    )
