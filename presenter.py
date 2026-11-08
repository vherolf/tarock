#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Tarock presentation window (read-only).

Shows the animated results of a tournament straight from the SQLite database
written by the data-entry tool (tarockmanager.py). This program never writes
to the database: it opens it read-only, so SQLite itself rejects any write.
The window updates live when the data-entry tool saves.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication, QMessageBox

from tarock_core import db, ranking
from tarock_core.paths import DEFAULT_DB, ordinal
from tarock_presenter.automode import DEFAULT_CYCLE, Stage
from tarock_presenter.pages import MATPLOTLIB_OK
from tarock_presenter.window import GraphWindow


# ----------------------------------------------------------------------
def read_standings(conn, tournament: int) -> tuple[ranking.Standings, list[str]]:
    names = db.players(conn, tournament)
    games = db.games(conn, tournament)
    return ranking.compute(games, names), db.check(conn, tournament)


def open_source(db_path: Path, tournament: int | None):
    """Open the database read-only. Returns (connection, tournament number)."""
    conn = db.open_ro(db_path)
    if tournament is None:
        tournament = db.latest_tournament(conn)
        if tournament is None:
            raise SystemExit(f"No tournaments in {db_path}. Use the data-entry tool first.")
    elif tournament not in db.tournaments(conn):
        raise SystemExit(f"Tournament {tournament} not found in {db_path}.")
    return conn, tournament


class LiveUpdater:
    """Polls the database and pushes new standings into the window.

    SQLite's data_version changes whenever another connection (the data-entry
    tool) commits, so an idle poll is one trivial query. The connection is
    read-only; this class never writes.
    """

    def __init__(self, conn, tournament: int, window: "GraphWindow", interval_ms: int = 1000) -> None:
        self._conn, self._tournament, self._window = conn, tournament, window
        self._version = self._data_version()
        self._base_title = window.windowTitle()
        self._timer = QTimer(window)
        self._timer.timeout.connect(self.poll)
        self._timer.start(interval_ms)

    def _data_version(self) -> int:
        return self._conn.execute("PRAGMA data_version").fetchone()[0]

    def poll(self) -> None:
        try:
            version = self._data_version()
            if version == self._version:
                return
            standings, problems = read_standings(self._conn, self._tournament)
        except Exception as exc:  # e.g. database briefly locked or file replaced - retry next tick
            print(f"live update skipped: {exc}", file=sys.stderr)
            return
        self._version = version
        self._window.setWindowTitle(
            self._base_title + (" - DATA PROBLEMS, ranking may be wrong" if problems else "")
        )
        if problems:
            print("data problems:\n  " + "\n  ".join(problems), file=sys.stderr)
        self._window.update_standings(standings)


def main() -> None:
    parser = argparse.ArgumentParser(description="Tarock presentation window (read-only)")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite database (default: %(default)s)")
    parser.add_argument(
        "--tournament", "-t", type=int, default=None, metavar="N",
        help="Tournament number to show. Shows the latest if omitted.",
    )
    parser.add_argument(
        "--speed-auto-mode", "-s", type=float, default=1.0, metavar="X",
        dest="auto_speed",
        help="Auto-mode speed multiplier (2.0 = twice as slow, 0.5 = twice as fast, default 1.0).",
    )
    parser.add_argument(
        "--auto-resume", "-r", type=int, default=180, metavar="SEC",
        dest="auto_resume_s",
        help="Seconds of inactivity on the compare page before auto mode resumes (default 180).",
    )
    parser.add_argument(
        "--auto-stages", default=",".join(s.value for s in DEFAULT_CYCLE), metavar="LIST",
        help="Comma-separated stages auto mode cycles through, from: "
             + ", ".join(s.value for s in Stage) + " (default: %(default)s).",
    )
    args, qt_args = parser.parse_known_args()

    if not MATPLOTLIB_OK:
        raise SystemExit("matplotlib is required:  pip install matplotlib")
    try:
        cycle = tuple(Stage(name.strip()) for name in args.auto_stages.split(",") if name.strip())
    except ValueError as exc:
        raise SystemExit(f"--auto-stages: {exc}")
    if not cycle:
        raise SystemExit("--auto-stages needs at least one stage")

    conn, tournament = open_source(args.db, args.tournament)
    standings, problems = read_standings(conn, tournament)
    if not standings.rows:
        print(f"Tournament {tournament} has no results yet - showing an empty presentation.")

    app = QApplication([sys.argv[0]] + qt_args)
    app.setFont(QFont("Noto Serif"))
    if problems:
        QMessageBox.warning(
            None, "Data problems found",
            "The database has inconsistencies; the shown ranking may be wrong:\n\n" + "\n".join(problems),
        )
    win = GraphWindow(
        standings,
        title=f"{ordinal(tournament)} Pony Tarock Championship",
        auto_speed=args.auto_speed,
        auto_resume_s=args.auto_resume_s,
        auto_cycle=cycle,
    )
    win.show()
    updater = LiveUpdater(conn, tournament, win)  # noqa: F841 - kept alive for the timer
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
