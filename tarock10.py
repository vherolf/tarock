#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PyQt6 application – 4‑player table recorder

New features added:
* Two columns on the left panel (Number | Name).
* “Save Mapping” writes the mapping to *player_numbers.csv*.
* **Load Mapping** button reloads the file and updates the UI.
* Print out of results now includes names from mapping instead of numbers
"""

import sys
import csv
from pathlib import Path

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
)
# Import QShortcut on the same line as requested
from PyQt6.QtGui import QIntValidator, QKeySequence, QShortcut, QFont
from PyQt6.QtCore import Qt


class MainWindow(QWidget):
    CSV_FILE = Path("result.csv")
    MAP_FILE = Path("player_numbers.csv")

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Tarock Tournament Manager")
        
        # Set font size to 18pt
        font = QFont()
        font.setPointSize(18)
        self.setFont(font)
        
        # Data storage (list of dicts)
        self.entries: list[dict] = []
        self.current_index: int = -1

        self._build_ui()
        self._load_mapping_from_file()      # ← load mapping first
        self._load_from_file()              # then load table entries

        if self.entries:
            self.current_index = 0          # start with first entry
            self._populate_form(self.entries[0])
            self._display_current_card()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        """Create the whole UI – left / right panels."""
        outer_layout = QHBoxLayout()          # <--- split left / right

        # ---------- LEFT PANEL ----------
        left_panel = QWidget()
        left_grid = QGridLayout()
        left_grid.setSpacing(4)

        # 20 rows × 2 columns (Player Number | Name)
        self.mapping_edits: list[tuple[QLineEdit, QLineEdit]] = []   # (player_number_le, name_le)
        self.mapping: dict[int, str] = {}                            # player number → name

        for row in range(20):
            # Player Number column ----------------------------------------------------
            num_le = QLineEdit()
            num_le.setPlaceholderText(f"Player № {row+1}")          # “Player № 1”, “Player № 2”, …
            num_le.setValidator(QIntValidator(0, 9999))      # only integers
            left_grid.addWidget(num_le, row, 0)              # column 0

            # Name column -------------------------------------------------------
            name_le = QLineEdit()
            name_le.setPlaceholderText(f"Name {row+1}")     # “Name 1”, …
            left_grid.addWidget(name_le, row, 1)             # column 1

            self.mapping_edits.append((num_le, name_le))

        # Save‑mapping button ----------------------------------------------------
        save_btn = QPushButton("Save Mapping")
        save_btn.clicked.connect(self._save_mapping_to_file)

        # Load‑mapping button -----------------------------------------------------
        load_btn = QPushButton("Load Mapping")
        load_btn.clicked.connect(self._load_mapping_from_file)   # same slot as startup

        left_layout = QVBoxLayout()
        left_layout.addLayout(left_grid)
        left_layout.addWidget(save_btn)           # below the grid
        left_layout.addWidget(load_btn)           # new button right below Save
        left_panel.setLayout(left_layout)

        outer_layout.addWidget(left_panel)

        # ---------- RIGHT PANEL (original UI) ----------
        right_widget = QWidget()
        main_layout = QVBoxLayout()

        form_layout = QGridLayout()
        form_layout.setColumnStretch(0, 1)
        form_layout.setColumnStretch(1, 1)
        form_layout.setColumnStretch(2, 1)
        form_layout.setColumnStretch(3, 1)

        # ----- Round -----
        self.round_spin = QSpinBox()
        self.round_spin.setRange(1, 1000)
        self.round_spin.setValue(1)
        form_layout.addWidget(QLabel("Round:"), 0, 0)
        form_layout.addWidget(self.round_spin, 0, 1)

        # ----- Table number -----
        self.table_edit = QLineEdit()
        self.table_edit.setPlaceholderText("e.g. 12")
        self.table_edit.setValidator(QIntValidator(1, 9999))
        form_layout.addWidget(QLabel("Table Number:"), 0, 2)
        form_layout.addWidget(self.table_edit, 0, 3)

        # ----- Player Numbers & Points -----
        self.player_number_edits: list[QLineEdit] = []
        self.points_spins: list[QSpinBox] = []

        for i in range(4):
            player_num_le = QLineEdit()
            player_num_le.setPlaceholderText(f"Player Number {i + 1}")
            points_sb = QSpinBox()
            points_sb.setRange(-100, 100)
            points_sb.setValue(0)

            self.player_number_edits.append(player_num_le)
            self.points_spins.append(points_sb)

            # Player Number – first row
            form_layout.addWidget(player_num_le, 1, i)
            # Point – second row (under the name)
            form_layout.addWidget(
                QLabel("Points:"), 2, i, alignment=Qt.AlignmentFlag.AlignCenter
            )
            form_layout.addWidget(points_sb, 3, i)

        main_layout.addLayout(form_layout)

        # *Space between first and second row*
        main_layout.addSpacing(10)   # ~10 px  (original)
        main_layout.addSpacing(20)   # extra space – about twice a field height

        # ----- Status label -----
        self.status_lbl = QLabel()
        self.status_lbl.setStyleSheet("color: red")
        main_layout.addWidget(self.status_lbl)

        # ----- Buttons (Submit now comes first) -----
        btn_layout = QHBoxLayout()

        submit_btn = QPushButton("Submit")          # NEW position
        change_btn = QPushButton("Change")
        prev_btn   = QPushButton("Previous")
        next_btn   = QPushButton("Next")
        clear_btn  = QPushButton("Clear")
        delete_btn = QPushButton("Delete")

        # Connect the buttons to their slots
        submit_btn.clicked.connect(self._on_submit)
        change_btn.clicked.connect(self._on_change)
        prev_btn.clicked.connect(self._show_previous)
        next_btn.clicked.connect(self._show_next)
        clear_btn.clicked.connect(self._clear_fields)
        delete_btn.clicked.connect(self._delete_current)

        btn_layout.addWidget(submit_btn)      # submit first
        btn_layout.addWidget(change_btn)
        btn_layout.addWidget(prev_btn)
        btn_layout.addWidget(next_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(clear_btn)
        btn_layout.addWidget(delete_btn)

        main_layout.addLayout(btn_layout)

        # ------------------------------------------------------------------
        # *** GLOBAL SHORTCUTS ***
        prev_shortcut_win = QShortcut(QKeySequence("Ctrl+P"), self)
        prev_shortcut_mac = QShortcut(QKeySequence("Meta+P"), self)  # ⌘‑P on macOS
        prev_shortcut_win.activated.connect(self._show_previous)
        prev_shortcut_mac.activated.connect(self._show_previous)

        next_shortcut_win = QShortcut(QKeySequence("Ctrl+N"), self)
        next_shortcut_mac = QShortcut(QKeySequence("Meta+N"), self)  # ⌘‑N on macOS
        next_shortcut_win.activated.connect(self._show_next)
        next_shortcut_mac.activated.connect(self._show_next)

        submit_shortcut_win = QShortcut(QKeySequence("Ctrl+S"), self)
        submit_shortcut_mac = QShortcut(QKeySequence("Meta+S"), self)  # ⌘‑S on macOS
        submit_shortcut_win.activated.connect(self._on_submit)
        submit_shortcut_mac.activated.connect(self._on_submit)

        change_shortcut = QShortcut(QKeySequence("Ctrl+C"), self)
        change_shortcut.activated.connect(self._on_change)

        # ------------------------------------------------------------------
        # Exclude Clear, Delete, Previous & Next from tab order
        clear_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        delete_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        prev_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        next_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # ------------------------------------------------------------------
        # *** SUM / RANK BUTTON ***
        sum_btn = QPushButton("Sum / Rank")
        sum_btn.clicked.connect(self._on_sum_and_rank)
        btn_layout.insertWidget(btn_layout.count() - 1, sum_btn)

        # ------------------------------------------------------------------
        # Output display
        self.output_display = QTextEdit()
        self.output_display.setReadOnly(True)
        self.output_display.setPlaceholderText("Current card will appear here…")
        main_layout.addWidget(self.output_display)

        right_widget.setLayout(main_layout)
        outer_layout.addWidget(right_widget)

        self.setLayout(outer_layout)

    # ------------------------------------------------------------------
    def _save_mapping_to_file(self):
        """Write the current player number→name pairs to *player_numbers.csv*."""
        mapping = {}
        for num_le, name_le in self.mapping_edits:
            n_text = num_le.text().strip()
            p_text = name_le.text().strip()
            if not n_text or not p_text:
                continue
            try:
                num = int(n_text)
            except ValueError:
                continue
            mapping[num] = p_text

        self.mapping = mapping  # keep in memory as well
        # Write to CSV
        try:
            with open(self.MAP_FILE, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                # Write header
                writer.writerow(["Player_Number", "Player_Name"])
                for num, name in sorted(mapping.items()):
                    writer.writerow([num, name])
            self.status_lbl.setText(
                f"Mapping saved – {len(mapping)} pairs written to player_numbers.csv"
            )
        except OSError as exc:
            self.status_lbl.setText(f"Could not write player_numbers.csv: {exc}")

    # ------------------------------------------------------------------
    def _load_mapping_from_file(self):
        """Read *player_numbers.csv* (if it exists) and pre‑populate the fields."""
        if not self.MAP_FILE.exists():
            return

        try:
            with open(self.MAP_FILE, newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                # Skip header
                next(reader, None)
                for idx, row in enumerate(reader):
                    # Skip empty rows
                    if len(row) < 2:
                        continue
                    num_str, name = row[0].strip(), row[1].strip()
                    try:
                        num = int(num_str)
                    except ValueError:
                        continue

                    # Guard against running out of slots
                    if idx >= len(self.mapping_edits):
                        break

                    num_le, name_le = self.mapping_edits[idx]
                    num_le.setText(str(num))
                    name_le.setText(name)

        except Exception as exc:
            self.status_lbl.setText(f"Could not read player_numbers.csv: {exc}")

    # ------------------------------------------------------------------
    def _clear_fields(self) -> None:
        """Reset all widgets to their default state."""
        self.table_edit.clear()
        self.round_spin.setValue(1)
        for le, sb in zip(self.player_number_edits, self.points_spins):
            le.clear()
            sb.setValue(0)
        self.output_display.clear()
        self.status_lbl.clear()

    # ------------------------------------------------------------------
    def _on_submit(self) -> None:
        """Validate input and *always* add a new entry."""
        table_text = self.table_edit.text().strip()
        if not table_text.isdigit():
            self.status_lbl.setText("Table number must be an integer.")
            return
        table_number = int(table_text)

        round_number = self.round_spin.value()

        player_numbers = [le.text().strip() for le in self.player_number_edits]
        points = [sb.value() for sb in self.points_spins]

        if any(not n for n in player_numbers):
            self.status_lbl.setText("All four player number fields must be filled.")
            return

        entry = {
            "table": table_number,
            "round": round_number,
            "people": [
                {"name": name, "points": pt} for name, pt in zip(player_numbers, points)
            ],
        }

        self.entries.append(entry)
        self.current_index = len(self.entries) - 1
        self._populate_form(entry)
        self._display_current_card()
        self._save_to_file()

    # ------------------------------------------------------------------
    def _on_change(self) -> None:
        """Replace the current entry with the values in the form."""
        if self.current_index == -1:
            self.status_lbl.setText("No entry selected to change.")
            return

        table_text = self.table_edit.text().strip()
        if not table_text.isdigit():
            self.status_lbl.setText("Table number must be an integer.")
            return
        table_number = int(table_text)

        round_number = self.round_spin.value()

        player_numbers = [le.text().strip() for le in self.player_number_edits]
        points = [sb.value() for sb in self.points_spins]

        if any(not n for n in player_numbers):
            self.status_lbl.setText("All four player number fields must be filled.")
            return

        entry = {
            "table": table_number,
            "round": round_number,
            "people": [
                {"name": name, "points": pt} for name, pt in zip(player_numbers, points)
            ],
        }

        self.entries[self.current_index] = entry
        self._display_current_card()
        self._save_to_file()

    # ------------------------------------------------------------------
    def _show_previous(self) -> None:
        if not self.entries:
            self.status_lbl.setText("No entries stored yet.")
            return
        if self.current_index <= 0:
            self.status_lbl.setText("Already at the first entry.")
            return
        self.current_index -= 1
        self._populate_form(self.entries[self.current_index])
        self._display_current_card()
        self._save_to_file()

    # ------------------------------------------------------------------
    def _show_next(self) -> None:
        if not self.entries:
            self.status_lbl.setText("No entries stored yet.")
            return
        if self.current_index >= len(self.entries) - 1:
            self.status_lbl.setText("Already at the last entry.")
            return
        self.current_index += 1
        self._populate_form(self.entries[self.current_index])
        self._display_current_card()
        self._save_to_file()

    # ------------------------------------------------------------------
    def _delete_current(self) -> None:
        if not self.entries:
            self.status_lbl.setText("No entries to delete.")
            return

        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Delete entry #{self.current_index + 1}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        del self.entries[self.current_index]

        # Adjust index / UI
        if not self.entries:
            self.current_index = -1
            self._clear_fields()
            self.status_lbl.setText("All entries deleted.")
        else:
            if self.current_index >= len(self.entries):
                self.current_index = len(self.entries) - 1
            self._populate_form(self.entries[self.current_index])
            self._display_current_card()

        self._save_to_file()

    # ------------------------------------------------------------------
    def _display_current_card(self) -> None:
        """Show only the currently selected card in the text edit."""
        if self.current_index == -1 or not self.entries:
            self.output_display.clear()
            return

        entry = self.entries[self.current_index]
        lines = [f"Table: {entry['table']}", f"Round: {entry['round']}"]
        for i, person in enumerate(entry["people"], start=1):
            lines.append(f"{person['name']} – Points: {person['points']}")
        self.output_display.setPlainText("\n".join(lines))
        self.status_lbl.clear()

    # ------------------------------------------------------------------
    def _populate_form(self, entry: dict) -> None:
        """Fill the input widgets with *entry* data."""
        self.table_edit.setText(str(entry["table"]))
        self.round_spin.setValue(entry["round"])
        for le, sb, person in zip(
            self.player_number_edits, self.points_spins, entry["people"]
        ):
            le.setText(person["name"])
            sb.setValue(person["points"])

    # ------------------------------------------------------------------
    def _entries_to_csv(self) -> str:
        """Return all stored entries as a CSV‑style string."""
        header = (
            "Table,Round,"
            + ",".join(f"Player_Number{i+1},Points{i+1}" for i in range(4))
        )
        rows = [header]
        for entry in self.entries:
            values = [
                str(entry["table"]),
                str(entry["round"]),
            ]
            for person in entry["people"]:
                values.extend([person["name"], str(person["points"])])
            rows.append(",".join(values))
        return "\n".join(rows)

    # ------------------------------------------------------------------
    def _save_to_file(self) -> None:
        """Write the current CSV representation to disk and stdout."""
        csv_text = self._entries_to_csv()
        if csv_text:
            print(csv_text, flush=True)           # stdout
            try:
                with open(self.CSV_FILE, "w", newline="", encoding="utf-8") as f:
                    f.write(csv_text)
            except OSError as exc:
                self.status_lbl.setText(f"Failed to write {self.CSV_FILE}: {exc}")

    # ------------------------------------------------------------------
    def _load_from_file(self) -> None:
        """Try to read the persisted CSV file on start‑up."""
        if not self.CSV_FILE.exists():
            return
        try:
            with open(self.CSV_FILE, newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if not rows or len(rows) < 2:
                return

            header = rows[0]
            for row in rows[1:]:
                # Expected format: Table,Round,Player_Number1,Points1,Player_Number2,Points2,...
                table = int(row[0])
                round_ = int(row[1])
                people = []
                for i in range(4):
                    name = row[2 + 2 * i]
                    points = int(row[3 + 2 * i])
                    people.append({"name": name, "points": points})
                self.entries.append(
                    {"table": table, "round": round_, "people": people}
                )
        except Exception as exc:
            # If anything goes wrong we just ignore the file
            self.status_lbl.setText(f"Could not read {self.CSV_FILE}: {exc}")

    # ------------------------------------------------------------------
    # NEW SLOT: calculate totals and print ranking
    # ------------------------------------------------------------------
    def _on_sum_and_rank(self) -> None:
        """
        Aggregate points for each name across all entries,
        sort them by total score (high → low), and output a ranking.
        """
        if not self.entries:
            self.status_lbl.setText("No entries to rank.")
            return

        # Dictionary: {name: total_points}
        totals: dict[str, int] = {}

        for entry in self.entries:
            for person in entry["people"]:
                name = person["name"]
                pts = person["points"]
                totals[name] = totals.get(name, 0) + pts
            print(entry)
        # Sort by points descending; if tie → alphabetical
        sorted_totals = sorted(
            totals.items(),
            key=lambda kv: (-kv[1], kv[0]),
        )

        # Build ranking CSV string with player names
        lines = ["Rank,Player_Number,Player_Name,Total Points"]
        for rank, (name, total) in enumerate(sorted_totals, start=1):
            # Get player name from mapping if available, otherwise use player number
            player_name = self.mapping.get(int(name), name) if name.isdigit() else name
            lines.append(f"{rank},{name},{player_name},{total}")

        ranking_csv = "\n".join(lines)

        # Print to stdout (so you see it immediately)
        print(ranking_csv, flush=True)

        # Write to ranking.csv for later reference
        try:
            with open("ranking.csv", "w", encoding="utf-8") as f:
                f.write(ranking_csv)
        except OSError as exc:
            self.status_lbl.setText(f"Could not write ranking.csv: {exc}")

        # Give the user a visual hint that the operation succeeded
        self.status_lbl.setText("Ranking generated – see console / ranking.csv.")


# ----------------------------------------------------------------------
def main() -> None:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.resize(1000, 600)          # Wider to accommodate left panel
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
