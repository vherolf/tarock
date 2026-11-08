#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Tarock data-entry tool.

Records players and table results in the SQLite database - the single source
of truth. The presentation tool (presenter.py) reads the same database
read-only. After every change this tool also writes a CSV copy
(result / player_numbers / ranking) to tournaments/<N>/ so ranking.csv can
never be stale; that copy is what gets committed for the GitHub Pages site.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Callable, TypeVar

from tarock_core import csv_io, db, html_export, html_views, ranking, sync, testdata
from tarock_core.paths import DATA_ROOT, DEFAULT_DB, ordinal, sibling_program

from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QPushButton,
    QTextEdit,
    QMessageBox,
    QScrollArea,
)
from PyQt6.QtGui import QColor, QIntValidator, QKeySequence, QPalette, QShortcut, QFont
from PyQt6.QtCore import Qt


MIN_MAPPING_ROWS = 20   # rows in the mapping panel; it grows when a tournament has more players

T = TypeVar("T")


class StartupError(Exception):
    """The tournament's CSV files are unusable, so the tool refuses to open it (the database is left untouched)."""

    def __init__(self, tournament: int, csv_dir: Path, errors: list[str]) -> None:
        shown = errors[:15] + ([f"... and {len(errors) - 15} more"] if len(errors) > 15 else [])
        self.message = (
            f"The CSV files of tournament {tournament} ({csv_dir}) cannot be used, so nothing was changed.\n"
            "The CSV files are the master copy - fix these problems (or move the folder away) and start again:\n\n"
            + "\n".join(f"  - {e}" for e in shown)
        )
        super().__init__(self.message)


class PlayerNumberSpin(QSpinBox):
    """Player-number spin box that can be empty (shown blank), unlike a plain QSpinBox."""

    EMPTY = -1

    def __init__(self) -> None:
        super().__init__()
        self.setRange(self.EMPTY, 9999)
        self.setSpecialValueText(" ")  # what the EMPTY value looks like
        self.setValue(self.EMPTY)

    def number(self) -> int | None:
        return None if self.value() == self.EMPTY else self.value()

    def set_number(self, number: int | None) -> None:
        self.setValue(self.EMPTY if number is None else number)

    def stepBy(self, steps: int) -> None:
        # from blank, the first up-click gives player 1 (not 0)
        if self.value() == self.EMPTY and steps > 0:
            self.setValue(1 + (steps - 1))
        else:
            super().stepBy(steps)


class MainWindow(QWidget):
    def __init__(self, db_path: Path, tournament: int, notice: str | None = None) -> None:
        super().__init__()
        self._notice = notice            # extra start-up message, e.g. 'test data regenerated'
        self._db_path = db_path
        self._tournament = tournament
        self._export_dir = db_path.parent / str(tournament)
        self._conn = db.open_rw(db_path)
        # The CSV files are the master copy: make the database match them before anything is shown.
        self._startup = sync.sync_tournament(self._conn, tournament, self._export_dir, db_path.parent / "backups")
        if self._startup.action == "invalid":
            self._conn.close()
            raise StartupError(tournament, self._export_dir, self._startup.errors)
        db.ensure_tournament(self._conn, tournament)
        self._tournament_title = f"{ordinal(tournament)} Pony Tarock Championship"
        self.setWindowTitle(f"Tarock Data Entry - tournament {tournament}")

        font = QFont("Noto Serif")
        font.setPointSize(18)
        self.setFont(font)

        self.games: list[db.Game] = []
        self.current_index: int = -1
        self._form_key: tuple[int, int] | None = None  # (round, table) the form was last loaded for

        self._build_ui()
        self._load_mapping()
        self._reload_games()
        if self.games:
            self.current_index = 0
            self._populate_form(self.games[0])
            self._display_current_card()
        self._report_problems()
        self._report_startup()

    def _build_ui(self) -> None:
        header = QLabel(self._tournament_title)
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setStyleSheet(
            "font-size: 28px; font-weight: bold; color: white;"
            " background-color: #CC0000; padding: 10px; border-radius: 8px;"
        )

        panels = QHBoxLayout()
        left = self._build_left_panel()
        # Player mapping keeps a modest width; the entry form gets the rest when maximized.
        left.setMinimumWidth(330)
        left.setMaximumWidth(400)
        panels.addWidget(left, 1)
        panels.addWidget(self._build_right_panel(), 4)

        outer_layout = QVBoxLayout()
        outer_layout.setSpacing(8)
        outer_layout.addWidget(header)
        outer_layout.addLayout(panels)
        self.setLayout(outer_layout)

    def _add_mapping_row(self) -> None:
        row = len(self.mapping_edits)
        num_le = QLineEdit()
        num_le.setPlaceholderText(f"Player № {row + 1}")
        num_le.setValidator(QIntValidator(0, 9999))
        num_le.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._mapping_grid.addWidget(num_le, row, 0)

        name_le = QLineEdit()
        name_le.setPlaceholderText(f"Name {row + 1}")
        name_le.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._mapping_grid.addWidget(name_le, row, 1)
        self.mapping_edits.append((num_le, name_le))

    def _build_left_panel(self) -> QWidget:
        container = QWidget()

        grid_widget = QWidget()
        left_grid = QGridLayout()
        left_grid.setSpacing(4)
        left_grid.setColumnStretch(0, 1)  # number: narrow
        left_grid.setColumnStretch(1, 3)  # name: wide

        self._mapping_grid = left_grid
        self.mapping_edits: list[tuple[QLineEdit, QLineEdit]] = []
        self.mapping: dict[int, str] = {}
        for _ in range(MIN_MAPPING_ROWS):
            self._add_mapping_row()

        grid_widget.setLayout(left_grid)

        scroll = QScrollArea()
        scroll.setWidget(grid_widget)
        scroll.setWidgetResizable(True)

        save_btn = QPushButton("Save Mapping")
        save_btn.clicked.connect(self._save_mapping)

        load_btn = QPushButton("Reload Mapping")
        load_btn.clicked.connect(self._load_mapping)

        layout = QVBoxLayout()
        layout.addWidget(scroll)
        layout.addWidget(save_btn)
        layout.addWidget(load_btn)
        container.setLayout(layout)
        return container

    def _build_right_panel(self) -> QWidget:
        widget = QWidget()
        main_layout = QVBoxLayout()
        main_layout.addLayout(self._build_form())
        main_layout.addSpacing(30)

        self.status_lbl = QLabel()
        main_layout.addWidget(self.status_lbl)
        main_layout.addLayout(self._build_buttons())

        self.output_display = QTextEdit()
        self.output_display.setReadOnly(True)
        self.output_display.setPlaceholderText("Current card will appear here…")
        self.output_display.setMinimumHeight(230)  # a result card (number above name, points below) fits without scrolling
        main_layout.addWidget(self.output_display)

        widget.setLayout(main_layout)
        return widget

    def _build_form(self) -> QGridLayout:
        form_layout = QGridLayout()
        for col in range(4):
            form_layout.setColumnStretch(col, 1)

        self.round_spin = QSpinBox()
        self.round_spin.setRange(1, 1000)
        self.round_spin.setValue(1)
        # Fire only on Enter / focus-out / arrows, not on every typed digit ("1" on the way to "12")
        self.round_spin.setKeyboardTracking(False)
        self.round_spin.valueChanged.connect(self._on_round_or_table_changed)
        form_layout.addWidget(QLabel("Round:"), 0, 0)
        form_layout.addWidget(self.round_spin, 0, 1)

        self.table_spin = QSpinBox()
        self.table_spin.setRange(1, 9999)
        self.table_spin.setValue(1)
        self.table_spin.setKeyboardTracking(False)  # see round_spin
        self.table_spin.valueChanged.connect(self._on_round_or_table_changed)
        form_layout.addWidget(QLabel("Table Number:"), 0, 2)
        form_layout.addWidget(self.table_spin, 0, 3)

        self.player_spins: list[PlayerNumberSpin] = []
        self.player_name_labels: list[QLabel] = []
        self.points_spins: list[QSpinBox] = []

        for i in range(4):
            player_num_le = PlayerNumberSpin()
            points_sb = QSpinBox()
            points_sb.setRange(-db.MAX_POINTS, db.MAX_POINTS)
            points_sb.setValue(0)

            name_lbl = QLabel()
            name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name_lbl.setMinimumHeight(name_lbl.fontMetrics().height() + 16)  # no jump when a name appears

            self.player_spins.append(player_num_le)
            self.player_name_labels.append(name_lbl)
            self.points_spins.append(points_sb)
            player_num_le.valueChanged.connect(self._update_name_labels)

            form_layout.addWidget(player_num_le, 1, i)
            form_layout.addWidget(name_lbl, 2, i)
            form_layout.addWidget(
                QLabel("Points:"), 3, i, alignment=Qt.AlignmentFlag.AlignCenter
            )
            form_layout.addWidget(points_sb, 4, i)

        return form_layout

    def _build_buttons(self) -> QHBoxLayout:
        submit_btn = QPushButton("Submit")
        prev_btn = QPushButton("Previous")
        next_btn = QPushButton("Next")
        clear_btn = QPushButton("Clear")
        delete_btn = QPushButton("Delete")
        sum_btn = QPushButton("Ranking")
        graph_btn = QPushButton("Present")
        export_btn = QPushButton("Export HTML")

        submit_btn.clicked.connect(self._on_submit)
        prev_btn.clicked.connect(self._show_previous)
        next_btn.clicked.connect(self._show_next)
        clear_btn.clicked.connect(self._clear_fields)
        delete_btn.clicked.connect(self._delete_current)
        sum_btn.clicked.connect(self._show_ranking)
        graph_btn.clicked.connect(self._on_present)
        export_btn.clicked.connect(self._on_export_html)

        for btn in (clear_btn, delete_btn, prev_btn, next_btn):
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # Ctrl+C intentionally omitted — conflicts with system copy shortcut
        QShortcut(QKeySequence("Ctrl+S"), self).activated.connect(self._on_submit)
        QShortcut(QKeySequence("Meta+S"), self).activated.connect(self._on_submit)
        QShortcut(QKeySequence("Ctrl+P"), self).activated.connect(self._show_previous)
        QShortcut(QKeySequence("Meta+P"), self).activated.connect(self._show_previous)
        QShortcut(QKeySequence("Ctrl+N"), self).activated.connect(self._show_next)
        QShortcut(QKeySequence("Meta+N"), self).activated.connect(self._show_next)

        layout = QHBoxLayout()
        layout.addWidget(submit_btn)
        layout.addWidget(prev_btn)
        layout.addWidget(next_btn)
        layout.addWidget(sum_btn)
        layout.addStretch()
        layout.addWidget(graph_btn)
        layout.addWidget(export_btn)
        layout.addWidget(clear_btn)
        layout.addWidget(delete_btn)
        return layout

    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    def _set_status(self, text: str, error: bool = False) -> None:
        color = "red" if error else "green"
        self.status_lbl.setStyleSheet(f"color: {color}")
        self.status_lbl.setText(text)

    def _clear_status(self) -> None:
        self.status_lbl.setStyleSheet("")
        self.status_lbl.clear()

    # ------------------------------------------------------------------
    def _reload_games(self) -> None:
        self.games = db.games(self._conn, self._tournament)

    def _save(self, write: Callable[[], T]) -> T:
        """Run a database write and the CSV export as ONE atomic step.

        The CSV files are the master copy, so a change counts as saved only if they were written too.
        If they cannot be written (disk full, read-only folder) the database change is rolled back and
        nothing is saved - the two can never disagree. Raises db.ValidationError with a user-facing message.
        """
        try:
            with db.transaction(self._conn):
                result = write()
                csv_io.export_tournament(self._conn, self._tournament, self._export_dir)
        except OSError as exc:
            raise db.ValidationError(f"NOT saved - the CSV files could not be written: {exc}") from exc
        self._reload_games()
        return result

    def _export_csv(self) -> str | None:
        """Rewrite the CSV files from the database (no data change). Returns an error text on failure."""
        try:
            csv_io.export_tournament(self._conn, self._tournament, self._export_dir)
        except OSError as exc:
            return str(exc)
        return None

    def _report_startup(self) -> None:
        """Tell the user what the start-up synchronisation with the CSV files did."""
        result = self._startup
        notes = []
        if result.action == "rebuilt":
            notes.append(f"Database rebuilt from the CSV files ({result.games} games).")
        elif result.action == "exported":
            notes.append("CSV files created from the database (there were none yet).")
        if result.ranking_refreshed:
            notes.append("ranking.csv was out of date and has been regenerated.")
        if result.replaced_data:
            QMessageBox.warning(
                self, "Database replaced from the CSV files",
                f"The database held different data for tournament {self._tournament} than its CSV files.\n"
                "The CSV files are the master copy and have replaced it.\n\n"
                f"The old database was saved to:\n{result.backup}",
            )
        if self._notice:
            notes.append(self._notice)
        if result.warnings:
            self._set_status(" ".join(notes + [f"WARNING: {w}" for w in result.warnings]), error=True)
        elif notes:
            self._set_status(" ".join(notes))

    def _report_problems(self) -> None:
        problems = db.check(self._conn, self._tournament)
        if problems:
            QMessageBox.warning(self, "Data problems found", "\n".join(problems))

    def _update_name_labels(self, *_) -> None:
        """Show the registered name under each player-number field."""
        # font/palette instead of a stylesheet, so the labels keep the form's font size
        bold = QFont(self.font())
        bold.setBold(True)
        for spin, lbl in zip(self.player_spins, self.player_name_labels):
            number = spin.number()
            known = number is not None and number in self.mapping
            lbl.setFont(bold if known else self.font())
            pal = lbl.palette()
            pal.setColor(QPalette.ColorRole.WindowText, QColor("#000000" if known else "#b00020"))
            lbl.setPalette(pal)
            if number is None:
                lbl.clear()
            else:
                lbl.setText(self.mapping[number] if known else "unknown player")

    def _name(self, pnum: int) -> str:
        return self.mapping.get(pnum, str(pnum))

    # ------------------------------------------------------------------
    def _read_mapping_fields(self) -> dict[int, str] | None:
        mapping: dict[int, str] = {}
        for num_le, name_le in self.mapping_edits:
            n_text, name = num_le.text().strip(), name_le.text().strip()
            if not n_text and not name:
                continue
            if not n_text or not name:
                self._set_status("Every mapping row needs both a number and a name.", error=True)
                return None
            num = int(n_text)
            if num in mapping:
                self._set_status(f"Player number {num} appears twice in the mapping.", error=True)
                return None
            mapping[num] = name
        return mapping

    def _save_mapping(self) -> None:
        mapping = self._read_mapping_fields()
        if mapping is None:
            return
        try:
            self._save(lambda: db.set_players(self._conn, self._tournament, mapping))
        except db.ValidationError as exc:
            self._set_status(str(exc), error=True)
            return
        self.mapping = mapping
        self._update_name_labels()
        self._set_status(f"Mapping saved - {len(mapping)} players.")

    def _load_mapping(self) -> None:
        self.mapping = db.players(self._conn, self._tournament)
        self._update_name_labels()
        while len(self.mapping_edits) < len(self.mapping):   # every stored player must be visible,
            self._add_mapping_row()                            # or Save Mapping would delete the hidden ones
        for num_le, name_le in self.mapping_edits:
            num_le.clear()
            name_le.clear()
        for (num_le, name_le), (num, name) in zip(self.mapping_edits, self.mapping.items()):
            num_le.setText(str(num))
            name_le.setText(name)

    # ------------------------------------------------------------------
    def _read_form(self) -> tuple[int, int, list[tuple[int, int]]] | None:
        """Parse the form widgets. Business rules are checked by db.save_game."""
        nums = [spin.number() for spin in self.player_spins]
        if any(n is None for n in nums):
            self._set_status("All four player number fields must be filled.", error=True)
            return None
        seats = [(n, sb.value()) for n, sb in zip(nums, self.points_spins)]
        return self.round_spin.value(), self.table_spin.value(), seats

    def _clear_fields(self) -> None:
        self._form_key = None
        self.table_spin.setValue(1)
        self.round_spin.setValue(1)
        for spin, sb in zip(self.player_spins, self.points_spins):
            spin.set_number(None)
            sb.setValue(0)
        self.output_display.clear()
        self._clear_status()

    # ------------------------------------------------------------------
    def _on_submit(self) -> None:
        form = self._read_form()
        if form is None:
            return
        round_, table, seats = form
        existing = next((g for g in self.games if (g.round, g.table) == (round_, table)), None)
        if existing is not None and not self._confirm_overwrite(existing, seats):
            self._set_status("Not saved - the existing result was kept.")
            return
        try:
            game_id = self._save(lambda: db.save_game(
                self._conn, self._tournament, *form,
                game_id=existing.id if existing else None,
            ))
        except db.ValidationError as exc:
            self._set_status(str(exc), error=True)
            return
        self.current_index = next(i for i, g in enumerate(self.games) if g.id == game_id)
        self._populate_form(self.games[self.current_index])
        self._display_current_card()
        self._set_status(f"{'Updated' if existing else 'Saved'} round {round_}, table {table}.")

    def _confirm_overwrite(self, existing: db.Game, new_seats: list[tuple[int, int]]) -> bool:
        """Warn that this round/table already has a result; True if the user wants to replace it."""
        def describe(seats) -> str:
            return "\n".join(f"   {self._name(p)} ({p}): {pts:+d}" for p, pts in seats)

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Result already exists")
        box.setText(f"Round {existing.round}, table {existing.table} already has a result.")
        box.setInformativeText("Do you want to overwrite it?")
        box.setDetailedText(
            f"Stored result:\n{describe(existing.seats)}\n\nNew result:\n{describe(new_seats)}"
        )
        overwrite = box.addButton("Overwrite", QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton("Keep existing", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)  # Enter must not overwrite by accident
        box.setEscapeButton(cancel)
        box.exec()
        return box.clickedButton() is overwrite

    def _select(self, index: int) -> None:
        """Show the stored game at `index` in the form and the card."""
        self.current_index = index
        self._populate_form(self.games[index])
        self._display_current_card()

    def _show_previous(self) -> None:
        if not self.games:
            self._set_status("No entries stored yet.", error=True)
            return
        if self.current_index == -1:          # blank form (new table): the last stored game is "before" it
            self._select(len(self.games) - 1)
        elif self.current_index == 0:
            self._set_status("Already at the first entry.", error=True)
        else:
            self._select(self.current_index - 1)

    def _show_next(self) -> None:
        if not self.games:
            self._set_status("No entries stored yet.", error=True)
            return
        if self.current_index == -1:          # blank form (new table): continue with the first stored game
            self._select(0)
        elif self.current_index >= len(self.games) - 1:
            self._set_status("Already at the last entry.", error=True)
        else:
            self._select(self.current_index + 1)

    def _delete_current(self) -> None:
        if not self.games:
            self._set_status("No entries to delete.", error=True)
            return
        if self.current_index == -1:          # blank form: there is no selected game (index -1 would be the LAST one)
            self._set_status("No entry selected - open a stored result first (Previous / Next).", error=True)
            return
        game = self.games[self.current_index]
        reply = QMessageBox.question(
            self, "Confirm Delete",
            f"Delete round {game.round}, table {game.table} (entry {self.current_index + 1} of {len(self.games)})?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self._save(lambda: db.delete_game(self._conn, game.id))
        except db.ValidationError as exc:
            self._set_status(str(exc), error=True)
            return
        if not self.games:
            self.current_index = -1
            self._clear_fields()
            self._set_status("All entries deleted.")
        else:
            self._select(min(self.current_index, len(self.games) - 1))
            self._set_status(f"Deleted round {game.round}, table {game.table}.")

    # ------------------------------------------------------------------
    def _display_current_card(self) -> None:
        if self.current_index == -1 or not self.games:
            self.output_display.clear()
            return
        game = self.games[self.current_index]
        self.output_display.setHtml(
            html_views.card_html(game, self.current_index + 1, len(self.games), self.mapping)
        )
        self._clear_status()

    def _on_round_or_table_changed(self, *_) -> None:
        """Round or table was changed in the form: load that table's stored game if there is one."""
        key = (self.round_spin.value(), self.table_spin.value())
        if key == self._form_key:
            return  # unchanged (e.g. focus just left the field) - keep any unsaved edits
        self._form_key = key
        for i, game in enumerate(self.games):
            if (game.round, game.table) == key:
                self.current_index = i
                self._populate_form(game)
                self._display_current_card()
                self._set_status(f"Loaded round {key[0]}, table {key[1]}.")
                return
        # No result for this round/table: empty form, ready for a new entry.
        # current_index = -1: nothing is selected until the new game is submitted.
        self.current_index = -1
        for spin, sb in zip(self.player_spins, self.points_spins):
            spin.set_number(None)
            sb.setValue(0)
        self.output_display.clear()
        self._set_status(f"Round {key[0]}, table {key[1]}: no result yet - enter the players.")
        self.player_spins[0].setFocus()

    def _populate_form(self, game: db.Game) -> None:
        self._form_key = (game.round, game.table)
        # block signals so loading a game doesn't trigger the round/table lookup again
        for w in (self.table_spin, self.round_spin):
            w.blockSignals(True)
        self.table_spin.setValue(game.table)
        self.round_spin.setValue(game.round)
        for w in (self.table_spin, self.round_spin):
            w.blockSignals(False)
        for spin, sb, (player, points) in zip(self.player_spins, self.points_spins, game.seats):
            spin.set_number(player)
            sb.setValue(points)

    # ------------------------------------------------------------------
    def _show_ranking(self) -> None:
        standings = ranking.compute(self.games, self.mapping)
        if not standings.rows:
            self._set_status("No entries to rank.", error=True)
            return
        self.output_display.setHtml(html_views.ranking_html(standings))
        error = self._export_csv()
        if error:
            self._set_status(f"Ranking shown, but the CSV files could not be written: {error}", error=True)
        else:
            self._set_status(f"Ranking saved to {self._export_dir / 'ranking.csv'}.")

    def _on_export_html(self) -> None:
        error = self._export_csv()
        if error:                                 # the page is built from the CSV files: never from stale ones
            self._set_status(f"Results page not exported: the CSV files could not be written ({error}).", error=True)
            return
        out_path = DATA_ROOT / "docs" / "index.html"
        try:
            html_export.build(self._export_dir, out_path)
        except Exception as exc:
            self._set_status(f"Could not export HTML: {exc}", error=True)
            return
        self._set_status(f"Results page exported to {out_path}.")

    def _on_present(self) -> None:
        """Open the read-only presentation tool as a separate process."""
        cmd = sibling_program("presenter", "presenter.py")
        try:
            subprocess.Popen(cmd + ["--db", str(self._db_path), "-t", str(self._tournament)])
        except OSError as exc:
            self._set_status(f"Could not start the presenter: {exc}", error=True)

    def closeEvent(self, event) -> None:
        self._conn.close()
        super().closeEvent(event)


# ----------------------------------------------------------------------
def default_tournament(db_path: Path) -> int:
    """The latest tournament - in the database or only as CSV files (e.g. after deleting the database)."""
    conn = db.open_rw(db_path)
    try:
        found = sync.available_tournaments(conn, db_path.parent)
    finally:
        conn.close()
    return found[-1] if found else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tarock data-entry tool")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite database (default: %(default)s)")
    parser.add_argument(
        "--tournament", "-t", type=int, default=None, metavar="N",
        help="Tournament number to open (created if new). Opens the latest if omitted.",
    )
    parser.add_argument(
        "--no-test-data", action="store_true",
        help="Do not regenerate the test tournaments 0 (14 players) and 1 (16 players) at start-up.",
    )
    parser.add_argument(
        "--test-seed", type=int, default=None, metavar="N",
        help="Seed for the generated test data (default: random). The seed is printed, so a data set can be reproduced.",
    )
    return parser


def refresh_test_data(args: argparse.Namespace) -> str | None:
    """Regenerate the test tournaments unless disabled. Returns a message for the user, or None."""
    if args.no_test_data:
        return None
    seed = testdata.refresh(args.db, args.test_seed)
    return f"Test tournaments 0 and 1 regenerated (seed {seed})."


def main() -> None:
    args, qt_args = build_parser().parse_known_args()

    notice = refresh_test_data(args)
    if notice:
        print(notice, flush=True)

    tournament = args.tournament if args.tournament is not None else default_tournament(args.db)

    app = QApplication([sys.argv[0]] + qt_args)
    app.setFont(QFont("Noto Serif"))
    try:
        win = MainWindow(args.db, tournament, notice if tournament in testdata_numbers() else None)
    except StartupError as exc:
        QMessageBox.critical(None, "Cannot open tournament", exc.message)
        sys.exit(1)
    win.resize(1000, 600)
    win.show()
    sys.exit(app.exec())


def testdata_numbers() -> set[int]:
    return {number for number, _ in testdata.TEST_TOURNAMENTS}


if __name__ == "__main__":
    main()
