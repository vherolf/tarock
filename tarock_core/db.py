"""SQLite storage for tournaments - the single source of truth.

* Data entry opens the database read/write via `open_rw`.
* Presentation opens it with `open_ro` (SQLite refuses every write).

Integrity is enforced twice: `validate_game` gives friendly messages, and the
schema constraints (foreign keys, UNIQUE, CHECK) are the backstop so bad data
cannot get in even through a bug.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

SCHEMA_VERSION = 1

MAX_POINTS = 1000   # a player's points in one game must be within +/- this

SCHEMA = f"""
CREATE TABLE tournament (
    number     INTEGER PRIMARY KEY CHECK (number >= 0),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE player (
    tournament INTEGER NOT NULL REFERENCES tournament(number) ON DELETE CASCADE,
    number     INTEGER NOT NULL CHECK (number BETWEEN 0 AND 9999),
    name       TEXT    NOT NULL CHECK (length(trim(name)) > 0),
    PRIMARY KEY (tournament, number),
    UNIQUE (tournament, name COLLATE NOCASE)
);

CREATE TABLE game (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament INTEGER NOT NULL REFERENCES tournament(number) ON DELETE CASCADE,
    round      INTEGER NOT NULL CHECK (round >= 1),
    table_no   INTEGER NOT NULL CHECK (table_no >= 1),
    UNIQUE (tournament, round, table_no),
    UNIQUE (id, tournament, round)
);

CREATE TABLE result (
    game_id    INTEGER NOT NULL,
    tournament INTEGER NOT NULL,
    round      INTEGER NOT NULL,
    seat       INTEGER NOT NULL CHECK (seat BETWEEN 1 AND 4),
    player     INTEGER NOT NULL,
    points     INTEGER NOT NULL CHECK (points BETWEEN -{MAX_POINTS} AND {MAX_POINTS}),
    PRIMARY KEY (game_id, seat),
    -- a player sits at exactly one table per round
    UNIQUE (tournament, round, player),
    FOREIGN KEY (game_id, tournament, round)
        REFERENCES game(id, tournament, round) ON DELETE CASCADE,
    -- only registered players can score; a player with results cannot be removed
    FOREIGN KEY (tournament, player)
        REFERENCES player(tournament, number) ON DELETE RESTRICT
);
"""


class ValidationError(ValueError):
    """Raised for input that must not be stored. The message is user-facing."""


@dataclass(frozen=True)
class Game:
    id: int
    round: int
    table: int
    seats: tuple[tuple[int, int], ...]  # ((player, points) x 4), in seat order


def _connect(target: str, uri: bool) -> sqlite3.Connection:
    conn = sqlite3.connect(target, uri=uri, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def open_rw(path: Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = _connect(str(path), uri=False)
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == 0:
        with _atomic(conn):
            conn.executescript(SCHEMA)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    elif version != SCHEMA_VERSION:
        conn.close()
        raise RuntimeError(f"{path}: unsupported schema version {version}")
    conn.execute("PRAGMA journal_mode = WAL")  # readers never block the writer
    return conn


def open_ro(path: Path) -> sqlite3.Connection:
    """Read-only connection: any write attempt raises sqlite3.OperationalError."""
    path = Path(path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Database not found: {path}")
    conn = _connect(f"file:{path}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only = ON")
    return conn


# ------------------------------------------------------------ transactions --
@contextmanager
def transaction(conn: sqlite3.Connection):
    """Group several writes (and anything done alongside them) into ONE atomic step.

    Takes the write lock up front, commits when the block ends, rolls everything back if it raises.
    Used by the data-entry tool so a database change and its CSV export succeed or fail together.
    """
    if conn.in_transaction:
        raise RuntimeError("transactions cannot be nested")
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


@contextmanager
def _atomic(conn: sqlite3.Connection):
    """Commit-or-rollback around one write - unless a surrounding `transaction` owns the commit."""
    if conn.in_transaction:
        yield
    else:
        with conn:
            yield


# ---------------------------------------------------------------- queries --
def tournaments(conn: sqlite3.Connection) -> list[int]:
    return [r[0] for r in conn.execute("SELECT number FROM tournament ORDER BY number")]


def latest_tournament(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT max(number) FROM tournament").fetchone()
    return row[0]


def ensure_tournament(conn: sqlite3.Connection, number: int) -> None:
    with _atomic(conn):
        conn.execute("INSERT OR IGNORE INTO tournament(number) VALUES (?)", (number,))


def players(conn: sqlite3.Connection, tournament: int) -> dict[int, str]:
    rows = conn.execute(
        "SELECT number, name FROM player WHERE tournament = ? ORDER BY number", (tournament,)
    )
    return {r["number"]: r["name"] for r in rows}


def games(conn: sqlite3.Connection, tournament: int) -> list[Game]:
    out: list[Game] = []
    for g in conn.execute(
        "SELECT id, round, table_no FROM game WHERE tournament = ? ORDER BY id", (tournament,)
    ).fetchall():
        seats = tuple(
            (r["player"], r["points"])
            for r in conn.execute(
                "SELECT player, points FROM result WHERE game_id = ? ORDER BY seat", (g["id"],)
            )
        )
        out.append(Game(g["id"], g["round"], g["table_no"], seats))
    return out


# ----------------------------------------------------------------- writes --
def set_players(conn: sqlite3.Connection, tournament: int, mapping: dict[int, str]) -> None:
    """Replace the player list. Players that already have results cannot be removed."""
    names = [n.strip().casefold() for n in mapping.values()]
    if any(not n for n in names):
        raise ValidationError("Player names must not be empty.")
    if len(set(names)) != len(names):
        raise ValidationError("Player names must be unique.")
    for num in mapping:
        if not 0 <= num <= 9999:
            raise ValidationError(f"Player number {num} is out of range (0-9999).")
    ensure_tournament(conn, tournament)
    try:
        with _atomic(conn):
            # rename in two phases so swapping names never trips the UNIQUE constraint
            existing = players(conn, tournament)
            for num in existing:
                if num not in mapping:
                    conn.execute(
                        "DELETE FROM player WHERE tournament = ? AND number = ?", (tournament, num)
                    )
            for num in existing:
                if num in mapping:
                    conn.execute(
                        "UPDATE player SET name = ? WHERE tournament = ? AND number = ?",
                        (f"~renaming-{num}~", tournament, num),
                    )
            for num, name in mapping.items():
                conn.execute(
                    "INSERT INTO player(tournament, number, name) VALUES (?,?,?) "
                    "ON CONFLICT(tournament, number) DO UPDATE SET name = excluded.name",
                    (tournament, num, name.strip()),
                )
    except sqlite3.IntegrityError as exc:
        if "FOREIGN KEY" in str(exc):
            raise ValidationError(
                "A player that already has results cannot be removed. Delete their games first."
            ) from exc
        raise ValidationError(f"Player list rejected: {exc}") from exc


def validate_game(
    conn: sqlite3.Connection,
    tournament: int,
    round_: int,
    table: int,
    seats: list[tuple[int, int]],
    game_id: int | None = None,
) -> None:
    if round_ < 1:
        raise ValidationError("Round must be 1 or higher.")
    if table < 1:
        raise ValidationError("Table number must be 1 or higher.")
    if len(seats) != 4:
        raise ValidationError("Exactly four players are required.")
    nums = [p for p, _ in seats]
    if len(set(nums)) != 4:
        raise ValidationError("All four player numbers must be unique.")
    if any(abs(points) > MAX_POINTS for _, points in seats):
        raise ValidationError(f"Points must be between -{MAX_POINTS} and {MAX_POINTS}.")
    registered = players(conn, tournament)
    unknown = [p for p in nums if p not in registered]
    if unknown:
        raise ValidationError(
            "Unknown player number(s): " + ", ".join(map(str, unknown))
            + ". Add them to the player mapping first."
        )
    total = sum(pts for _, pts in seats)
    if total != 0:
        raise ValidationError(f"Points must sum to 0 (current sum: {total:+d}).")
    dup = conn.execute(
        "SELECT 1 FROM game WHERE tournament=? AND round=? AND table_no=? AND id IS NOT ?",
        (tournament, round_, table, game_id),
    ).fetchone()
    if dup:
        raise ValidationError(
            f"Table {table} already has a result for round {round_}."
        )
    for p in nums:
        other = conn.execute(
            "SELECT g.table_no FROM result r JOIN game g ON g.id = r.game_id "
            "WHERE r.tournament=? AND r.round=? AND r.player=? AND g.id IS NOT ?",
            (tournament, round_, p, game_id),
        ).fetchone()
        if other:
            raise ValidationError(
                f"{registered[p]} ({p}) already played in round {round_} at table {other['table_no']}."
            )


def save_game(
    conn: sqlite3.Connection,
    tournament: int,
    round_: int,
    table: int,
    seats: list[tuple[int, int]],
    game_id: int | None = None,
) -> int:
    """Insert (game_id=None) or replace a game atomically; returns its id."""
    validate_game(conn, tournament, round_, table, seats, game_id)
    try:
        with _atomic(conn):
            if game_id is None:
                cur = conn.execute(
                    "INSERT INTO game(tournament, round, table_no) VALUES (?,?,?)",
                    (tournament, round_, table),
                )
                game_id = cur.lastrowid
            else:
                if not conn.execute(
                    "SELECT 1 FROM game WHERE id=? AND tournament=?", (game_id, tournament)
                ).fetchone():
                    raise ValidationError("The game to change no longer exists.")
                conn.execute("DELETE FROM result WHERE game_id = ?", (game_id,))
                conn.execute(
                    "UPDATE game SET round=?, table_no=? WHERE id=?", (round_, table, game_id)
                )
            conn.executemany(
                "INSERT INTO result(game_id, tournament, round, seat, player, points) "
                "VALUES (?,?,?,?,?,?)",
                [(game_id, tournament, round_, i + 1, p, pts) for i, (p, pts) in enumerate(seats)],
            )
    except sqlite3.IntegrityError as exc:
        raise ValidationError(f"Rejected by database: {exc}") from exc
    return game_id


def delete_game(conn: sqlite3.Connection, game_id: int) -> None:
    with _atomic(conn):
        conn.execute("DELETE FROM game WHERE id = ?", (game_id,))


# -------------------------------------------------------------- integrity --
def check(conn: sqlite3.Connection, tournament: int) -> list[str]:
    """Independent audit of stored data. An empty list means everything is consistent."""
    problems: list[str] = []
    for r in conn.execute("PRAGMA foreign_key_check"):
        problems.append(f"foreign key violation in table {r[0]}")
    for g in conn.execute(
        "SELECT g.id, g.round, g.table_no, count(r.seat) n, coalesce(sum(r.points),0) s "
        "FROM game g LEFT JOIN result r ON r.game_id = g.id "
        "WHERE g.tournament = ? GROUP BY g.id",
        (tournament,),
    ):
        label = f"round {g['round']} table {g['table_no']}"
        if g["n"] != 4:
            problems.append(f"{label}: {g['n']} players instead of 4")
        if g["s"] != 0:
            problems.append(f"{label}: points sum to {g['s']:+d}, not 0")
    return problems
