"""Keeps the SQLite database consistent with the CSV files - the CSV files win.

The CSV files in tournaments/<N>/ are the truth. The database is a working copy that enforces the
rules and feeds the presenter live; it can be deleted at any time and is rebuilt from the CSVs.

    sync_tournament()  - run at start-up of the data-entry tool: make the database match the CSVs
    check()            - read-only comparison (presenter warning, dry runs)

If the database holds different data for a tournament than its CSVs, the CSVs replace it - after
a copy of the whole database was saved to backups/ - so nothing is ever lost silently.
"""
from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import csv_io, db, ranking

MAX_BACKUPS = 20          # older backup files are pruned

# Normalised "what a tournament contains", comparable between CSV and database:
#   (players, [(round, table, seats), ...] in order)
State = tuple[dict[int, str], list[tuple[int, int, tuple[tuple[int, int], ...]]]]


@dataclass
class SyncResult:
    action: str                       # in_sync | rebuilt | exported | nothing | invalid
    errors: list[str] = field(default_factory=list)
    games: int = 0
    replaced_data: bool = False       # the database held different data that the CSVs replaced
    backup: Path | None = None        # where the old database was saved (only if replaced_data)
    ranking_refreshed: bool = False   # the derived ranking.csv was out of date and rewritten
    warnings: list[str] = field(default_factory=list)   # things that did not work but do not stop the start


def csv_files_present(csv_dir: Path) -> bool:
    """Both data files exist (result.csv and player_numbers.csv)."""
    return (csv_dir / csv_io.RESULT_FILE).exists() and (csv_dir / csv_io.PLAYERS_FILE).exists()


def _half_present(csv_dir: Path) -> list[str]:
    """If exactly one data file exists, say which is missing - saving would overwrite the survivor, so refuse."""
    have = [name for name in (csv_io.RESULT_FILE, csv_io.PLAYERS_FILE) if (csv_dir / name).exists()]
    if len(have) == 1:
        missing = csv_io.PLAYERS_FILE if have[0] == csv_io.RESULT_FILE else csv_io.RESULT_FILE
        return [f"{missing} is missing (only {have[0]} exists) - restore it, e.g. from git"]
    return []


def csv_tournament_numbers(base: Path) -> list[int]:
    """Tournament folders under `base` that hold CSV data."""
    if not base.exists():
        return []
    return sorted(int(d.name) for d in base.iterdir() if d.is_dir() and d.name.isdigit() and csv_files_present(d))


def available_tournaments(conn: sqlite3.Connection, base: Path) -> list[int]:
    """Tournaments that exist in the database and/or as CSV folders."""
    return sorted(set(db.tournaments(conn)) | set(csv_tournament_numbers(base)))


def _db_state(conn: sqlite3.Connection, tournament: int) -> State:
    return db.players(conn, tournament), [(g.round, g.table, g.seats) for g in db.games(conn, tournament)]


def _csv_state(parsed: csv_io.ParsedTournament) -> State:
    return dict(parsed.players), [(g.round, g.table, g.seats) for g in parsed.games]


def _has_data(state: State) -> bool:
    return bool(state[0] or state[1])


def _validate(parsed: csv_io.ParsedTournament, tournament: int) -> None:
    """Dry run against a scratch in-memory database: raises ImportErrors if any schema rule is broken."""
    scratch = db.open_rw(Path(":memory:"))
    try:
        csv_io.load_tournament(scratch, tournament, parsed)
    finally:
        scratch.close()


def check(conn: sqlite3.Connection, tournament: int, csv_dir: Path) -> tuple[str, list[str]]:
    """Read-only comparison. Returns (status, errors); status is one of
    in_sync | differs | no_csv | invalid."""
    if not csv_files_present(csv_dir):
        incomplete = _half_present(csv_dir)
        return ("invalid", incomplete) if incomplete else ("no_csv", [])
    try:
        parsed = csv_io.parse_tournament(csv_dir)
        _validate(parsed, tournament)
    except csv_io.ImportErrors as exc:
        return "invalid", exc.errors
    return ("in_sync" if _csv_state(parsed) == _db_state(conn, tournament) else "differs"), []


def backup_database(conn: sqlite3.Connection, backup_dir: Path, label: str) -> Path:
    """Save a consistent copy of the whole database (works while it is open) and prune old copies."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = backup_dir / f"tournaments-{stamp}-{label}.db"
    n = 1
    while dest.exists():
        dest = backup_dir / f"tournaments-{stamp}-{label}-{n}.db"
        n += 1
    target = sqlite3.connect(dest)
    try:
        conn.backup(target)
    finally:
        target.close()
    for old in sorted(backup_dir.glob("tournaments-*.db"))[:-MAX_BACKUPS]:
        old.unlink(missing_ok=True)
    return dest


def _refresh_ranking(conn: sqlite3.Connection, tournament: int, csv_dir: Path) -> bool:
    """ranking.csv is derived data: rewrite it if it does not match the tournament (never touches the data files)."""
    expected = csv_io.ranking_rows(ranking.compute(db.games(conn, tournament), db.players(conn, tournament)))
    path = csv_dir / csv_io.RANKING_FILE
    if path.exists():
        with open(path, newline="", encoding="utf-8") as f:
            if [[*row] for row in csv.reader(f)] == [[str(v) for v in row] for row in expected]:
                return False
    csv_io.export_ranking(conn, tournament, csv_dir)
    return True


def sync_tournament(
    conn: sqlite3.Connection, tournament: int, csv_dir: Path, backup_dir: Path | None = None
) -> SyncResult:
    """Make the database hold exactly what the CSV files say. Never loses data silently:

    * CSV files invalid           -> nothing is changed; the problems are returned (action "invalid")
    * database already matches    -> nothing is written (action "in_sync")
    * database lacks / differs    -> old database backed up (if it held data), tournament rebuilt ("rebuilt")
    * no CSV files but database has data -> the CSV files are created from the database ("exported")
    """
    if not csv_files_present(csv_dir):
        incomplete = _half_present(csv_dir)
        if incomplete:
            return SyncResult("invalid", errors=incomplete)
        if _has_data(_db_state(conn, tournament)):
            result = SyncResult("exported", games=len(db.games(conn, tournament)))
            try:
                csv_io.export_tournament(conn, tournament, csv_dir)
            except OSError as exc:
                result.warnings.append(f"the CSV files could not be created in {csv_dir}: {exc}")
            return result
        return SyncResult("nothing")

    try:
        parsed = csv_io.parse_tournament(csv_dir)
        _validate(parsed, tournament)
    except csv_io.ImportErrors as exc:
        return SyncResult("invalid", errors=exc.errors)

    current = _db_state(conn, tournament)
    if _csv_state(parsed) == current:
        result = SyncResult("in_sync", games=len(parsed.games))
        _refresh_ranking_safely(conn, tournament, csv_dir, result)
        return result

    result = SyncResult("rebuilt", games=len(parsed.games), replaced_data=_has_data(current))
    if result.replaced_data and backup_dir is not None and _on_disk(conn):
        result.backup = backup_database(conn, backup_dir, f"t{tournament}")
    try:
        csv_io.load_tournament(conn, tournament, parsed, replace=True)
    except csv_io.ImportErrors as exc:      # cannot happen after the dry run, but never fail silently
        return SyncResult("invalid", errors=exc.errors)
    _refresh_ranking_safely(conn, tournament, csv_dir, result)
    return result


def _refresh_ranking_safely(conn: sqlite3.Connection, tournament: int, csv_dir: Path, result: SyncResult) -> None:
    try:
        result.ranking_refreshed = _refresh_ranking(conn, tournament, csv_dir)
    except OSError as exc:
        result.warnings.append(f"ranking.csv is out of date and could not be rewritten: {exc}")


def _on_disk(conn: sqlite3.Connection) -> bool:
    return any(row[2] for row in conn.execute("PRAGMA database_list"))
