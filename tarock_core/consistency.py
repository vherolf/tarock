"""Consistency check of the committed CSV files.

The SQLite database is local; the CSVs in tournaments/<N>/ are what gets committed and
published. This verifies, without needing the database, that for each tournament:
  * result.csv + player_numbers.csv pass every rule of the real schema (players registered,
    4 per game, points sum to 0, one table/player per round, ...), and
  * ranking.csv equals the ranking computed from result.csv (so it is not stale or hand-edited).
"""
from __future__ import annotations

import csv
from pathlib import Path

from . import csv_io, db, ranking
from .paths import PUBLISHED_FILE

_HEADER = ["Rank", "Player_Number", "Player_Name", "Total_Points"]


def check_tournament_dir(directory: Path) -> list[str]:
    number = int(directory.name)
    problems: list[str] = []
    for name in ("result.csv", "player_numbers.csv", "ranking.csv"):
        if not (directory / name).exists():
            problems.append(f"missing {name}")
    if problems:
        return problems

    conn = db.open_rw(Path(":memory:"))
    try:
        csv_io.import_tournament(conn, number, directory)
    except csv_io.ImportErrors as exc:
        return [f"result/player files invalid: {e}" for e in exc.errors]
    standings = ranking.compute(db.games(conn, number), db.players(conn, number))
    expected = [(s.rank, s.player, s.name, s.total) for s in standings.rows]

    with open(directory / "ranking.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if not rows or rows[0] != _HEADER:
        return ["ranking.csv: unexpected header"]
    try:
        found = [(int(r[0]), int(r[1]), r[2], int(r[3])) for r in rows[1:] if r]
    except (ValueError, IndexError):
        return ["ranking.csv: unreadable rows"]

    if found != expected:
        problems.append("ranking.csv does not match result.csv (stale or edited by hand)")
        for e, fnd in zip(expected, found):
            if e != fnd:
                problems.append(f"   expected {e}, found {fnd}")
        if len(expected) != len(found):
            problems.append(f"   expected {len(expected)} rows, found {len(found)}")
    return problems


def check_all(base: Path) -> dict[str, list[str]]:
    """Check every tournament folder plus the published marker. Returns {label: problems}."""
    report: dict[str, list[str]] = {}
    for d in sorted((d for d in base.iterdir() if d.is_dir() and d.name.isdigit()), key=lambda d: int(d.name)):
        report[f"tournament {d.name}"] = check_tournament_dir(d)
    marker = base / PUBLISHED_FILE
    if marker.exists():
        text = marker.read_text(encoding="utf-8").strip()
        ok = text.isdigit() and (base / str(int(text)) / "ranking.csv").exists()
        report[PUBLISHED_FILE] = [] if ok else [f"{PUBLISHED_FILE} names {text!r}, which has no ranking.csv"]
    else:
        report[PUBLISHED_FILE] = [f"{PUBLISHED_FILE} is missing"]
    return report
