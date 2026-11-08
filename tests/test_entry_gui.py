"""Headless tests for the data-entry tool (tarockmanager.py), Qt 'offscreen' platform."""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

import tarockmanager as T  # noqa: E402
from tarock_core import consistency, db  # noqa: E402

NAMES = {i: f"P{i}" for i in range(1, 9)}


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dialogs(monkeypatch):
    """Replace modal dialogs: records what was shown, answers according to `answer`."""
    class Recorder:
        confirm_delete = True        # answer to "Delete ...?"
        overwrite = True             # answer to "Result already exists"
        shown: list = []

    rec = Recorder()
    rec.shown = []

    def question(parent, title, text, *args, **kwargs):
        rec.shown.append(("question", text))
        return QMessageBox.StandardButton.Yes if rec.confirm_delete else QMessageBox.StandardButton.No

    def warning(parent, title, text, *args, **kwargs):
        rec.shown.append(("warning", text))

    def exec_(box):
        rec.shown.append(("box", box.text(), box.detailedText(), box.defaultButton().text()))
        label = "Overwrite" if rec.overwrite else "Keep existing"
        box._clicked = next(b for b in box.buttons() if b.text() == label)
        return 0

    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(warning))
    monkeypatch.setattr(QMessageBox, "exec", exec_)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda box: box._clicked)
    return rec


@pytest.fixture
def make_window(app, tmp_path, dialogs):
    windows = []

    def factory(games=((1, 1, [(1, 5), (2, -5), (3, 0), (4, 0)]), (1, 2, [(5, 3), (6, -3), (7, 0), (8, 0)])),
                players=NAMES):
        path = tmp_path / f"t{len(windows)}.db"
        conn = db.open_rw(path)
        db.set_players(conn, 1, players)
        for round_, table, seats in games:
            db.save_game(conn, 1, round_, table, seats)
        conn.close()
        win = T.MainWindow(path, 1)
        win.show()
        windows.append(win)
        return win

    yield factory
    for win in windows:
        win.close()


def fill(win, players, points, round_=None, table=None):
    if round_ is not None:
        win.round_spin.setValue(round_)
    if table is not None:
        win.table_spin.setValue(table)
    for spin, number in zip(win.player_spins, players):
        spin.set_number(number)
    for box, value in zip(win.points_spins, points):
        box.setValue(value)


def stored(win):
    return db.games(win._conn, 1)


# ------------------------------------------------------------------ startup ----
def test_opens_with_first_game_loaded(make_window):
    win = make_window()
    assert len(win.games) == 2 and win.current_index == 0
    assert [s.number() for s in win.player_spins] == [1, 2, 3, 4]
    assert (win.round_spin.value(), win.table_spin.value()) == (1, 1)
    assert "Table 1" in win.output_display.toPlainText()


def test_empty_tournament_starts_blank(make_window):
    win = make_window(games=())
    assert win.current_index == -1 and win.games == []
    assert all(s.number() is None for s in win.player_spins)


def test_startup_warns_about_inconsistent_data(app, tmp_path, dialogs):
    path = tmp_path / "bad.db"
    conn = db.open_rw(path)
    db.set_players(conn, 1, NAMES)
    db.save_game(conn, 1, 1, 1, [(1, 5), (2, -5), (3, 0), (4, 0)])
    conn.execute("UPDATE result SET points = 9 WHERE seat = 1")
    conn.commit()
    conn.close()
    win = T.MainWindow(path, 1)
    assert any(kind == "warning" and "sum to" in text for kind, text, *_ in dialogs.shown)
    win.close()


# ------------------------------------------------------------------- submit ----
def test_submit_new_game_saves_selects_and_exports(make_window):
    win = make_window()
    fill(win, [1, 2, 3, 4], [6, -3, -3, 0], round_=2, table=1)
    win._on_submit()
    assert "Saved round 2, table 1" in win.status_lbl.text()
    assert len(stored(win)) == 3 and win.current_index == 2
    assert (win._export_dir / "result.csv").read_text().count("\n") == 4          # header + 3 games
    assert consistency.check_tournament_dir(win._export_dir) == []                # ranking.csv is in sync


@pytest.mark.parametrize("players,points,message", [
    ([1, 2, 3, 4], [1, 1, 1, 1], "sum to 0"),
    ([1, 1, 3, 4], [0, 0, 0, 0], "unique"),
    ([1, 2, 3, 99], [0, 0, 0, 0], "Unknown player"),
])
def test_submit_rejects_invalid_input_and_stores_nothing(make_window, players, points, message):
    win = make_window()
    fill(win, players, points, round_=2, table=1)
    win._on_submit()
    assert message in win.status_lbl.text()
    assert len(stored(win)) == 2


def test_submit_with_blank_player_field_is_rejected(make_window):
    win = make_window()
    fill(win, [1, 2, 3, 4], [0, 0, 0, 0], round_=2, table=1)
    win.player_spins[2].set_number(None)
    win._on_submit()
    assert "must be filled" in win.status_lbl.text() and len(stored(win)) == 2


def test_submit_of_existing_table_asks_and_keep_leaves_data_untouched(make_window, dialogs):
    win = make_window()
    dialogs.overwrite = False
    win.points_spins[0].setValue(8)
    win.points_spins[1].setValue(-8)
    win._on_submit()
    box = next(s for s in dialogs.shown if s[0] == "box")
    assert "Round 1, table 1 already has a result" in box[1]
    assert "Stored result" in box[2] and "New result" in box[2]
    assert box[3] == "Keep existing"                      # the safe answer is the default
    assert "kept" in win.status_lbl.text()
    assert stored(win)[0].seats[0] == (1, 5)


def test_submit_of_existing_table_overwrites_after_confirmation_without_duplicating(make_window, dialogs):
    win = make_window()
    dialogs.overwrite = True
    win.points_spins[0].setValue(8)
    win.points_spins[1].setValue(-8)
    win._on_submit()
    games = stored(win)
    assert len(games) == 2 and games[0].seats[:2] == ((1, 8), (2, -8))
    assert "Updated round 1, table 1" in win.status_lbl.text()


def test_submit_new_table_does_not_ask(make_window, dialogs):
    win = make_window()
    fill(win, [1, 2, 3, 4], [0, 0, 0, 0], round_=2, table=1)
    win._on_submit()
    assert not [s for s in dialogs.shown if s[0] == "box"]


# ------------------------------------------------ round/table field behaviour ----
def test_changing_table_loads_existing_result(make_window):
    win = make_window()
    win.table_spin.setValue(2)
    assert win.current_index == 1
    assert [s.number() for s in win.player_spins] == [5, 6, 7, 8]
    assert [b.value() for b in win.points_spins] == [3, -3, 0, 0]
    assert "Loaded round 1, table 2" in win.status_lbl.text()


def test_changing_to_a_new_table_blanks_the_form(make_window):
    win = make_window()
    win.table_spin.setValue(9)
    assert win.current_index == -1
    assert all(s.number() is None for s in win.player_spins)
    assert [b.value() for b in win.points_spins] == [0, 0, 0, 0]
    assert win.output_display.toPlainText() == ""
    assert "no result yet" in win.status_lbl.text()


def test_unsaved_edits_survive_when_round_and_table_do_not_change(make_window):
    win = make_window()
    win.points_spins[0].setValue(9)
    win._on_round_or_table_changed()                      # e.g. focus left the table field unchanged
    assert win.points_spins[0].value() == 9


# --------------------------------------------------------------- player names ----
def test_name_labels_follow_the_number_fields(make_window):
    win = make_window(games=())
    labels = lambda: [lbl.text() for lbl in win.player_name_labels]      # noqa: E731
    win.player_spins[0].set_number(5)
    win.player_spins[1].set_number(99)
    assert labels() == ["P5", "unknown player", "", ""]
    win.player_spins[1].set_number(None)
    assert labels()[1] == ""


def test_player_number_spin_blank_and_stepping(app):
    spin = T.PlayerNumberSpin()
    assert spin.number() is None and spin.text().strip() == ""
    spin.stepUp()
    assert spin.number() == 1                             # first click from blank gives player 1
    spin.stepDown()
    assert spin.number() == 0
    spin.stepDown()
    assert spin.number() is None                          # below 0 it is blank again
    spin.set_number(7)
    assert spin.number() == 7


# ------------------------------------------------------------------ navigation ----
def test_previous_and_next_walk_through_games_and_stop_at_the_ends(make_window):
    win = make_window()
    win._show_previous()
    assert "first entry" in win.status_lbl.text() and win.current_index == 0
    win._show_next()
    assert win.current_index == 1 and win.table_spin.value() == 2
    win._show_next()
    assert "last entry" in win.status_lbl.text() and win.current_index == 1
    win._show_previous()
    assert win.current_index == 0


def test_navigation_from_the_blank_form(make_window):
    """Regression: with a blank (new-table) form, Previous refused and Next skipped around."""
    win = make_window()
    win.table_spin.setValue(9)
    win._show_previous()
    assert win.current_index == 1                         # the last stored game
    win.table_spin.setValue(9)
    win._show_next()
    assert win.current_index == 0                         # the first stored game


def test_navigation_without_games(make_window):
    win = make_window(games=())
    win._show_previous()
    assert "No entries" in win.status_lbl.text()
    win._show_next()
    assert "No entries" in win.status_lbl.text()


# ---------------------------------------------------------------------- delete ----
def test_delete_removes_the_shown_game_after_confirmation(make_window, dialogs):
    win = make_window()
    win._delete_current()
    assert "round 1, table 1" in dialogs.shown[-1][1]
    games = stored(win)
    assert len(games) == 1 and (games[0].round, games[0].table) == (1, 2)
    assert win.current_index == 0 and win.table_spin.value() == 2           # now shows the remaining game
    assert consistency.check_tournament_dir(win._export_dir) == []


def test_delete_declined_keeps_everything(make_window, dialogs):
    win = make_window()
    dialogs.confirm_delete = False
    win._delete_current()
    assert len(stored(win)) == 2


def test_delete_from_the_blank_form_deletes_nothing(make_window, dialogs):
    """Regression: index -1 used to delete the LAST stored game while the form showed nothing."""
    win = make_window()
    win.table_spin.setValue(9)
    win._delete_current()
    assert len(stored(win)) == 2
    assert "No entry selected" in win.status_lbl.text()
    assert not [s for s in dialogs.shown if s[0] == "question"]              # not even asked


def test_deleting_the_last_game_blanks_the_form(make_window):
    win = make_window(games=((1, 1, [(1, 5), (2, -5), (3, 0), (4, 0)]),))
    win._delete_current()
    assert stored(win) == [] and win.current_index == -1
    assert "All entries deleted" in win.status_lbl.text()


# --------------------------------------------------------------------- mapping ----
def test_mapping_panel_shows_registered_players(make_window):
    win = make_window()
    rows = [(n.text(), m.text()) for n, m in win.mapping_edits if n.text()]
    assert rows == [(str(k), v) for k, v in NAMES.items()]


def test_save_mapping_adds_and_renames_players(make_window):
    win = make_window()
    free = next(i for i, (n, _) in enumerate(win.mapping_edits) if not n.text())
    win.mapping_edits[free][0].setText("9")
    win.mapping_edits[free][1].setText("Newcomer")
    win.mapping_edits[0][1].setText("Renamed")
    win._save_mapping()
    assert db.players(win._conn, 1)[9] == "Newcomer" and db.players(win._conn, 1)[1] == "Renamed"
    assert "Mapping saved" in win.status_lbl.text()
    assert win.player_name_labels[0].text() == "Renamed"                      # the form picks up the new name
    assert consistency.check_tournament_dir(win._export_dir) == []


@pytest.mark.parametrize("edit,message", [
    (lambda rows: (rows[1][1].setText("p1")), "unique"),                     # same name as player 1 (case-insensitive)
    (lambda rows: rows[1][0].setText("1"), "twice"),                         # same number twice
    (lambda rows: rows[1][1].clear(), "needs both"),                         # number without a name
])
def test_save_mapping_rejects_bad_input(make_window, edit, message):
    win = make_window()
    edit(win.mapping_edits)
    win._save_mapping()
    assert message in win.status_lbl.text()
    assert db.players(win._conn, 1) == NAMES


def test_save_mapping_cannot_remove_a_player_with_results(make_window):
    win = make_window()
    win.mapping_edits[0][0].clear()
    win.mapping_edits[0][1].clear()                                          # player 1 has a result
    win._save_mapping()
    assert "already has results" in win.status_lbl.text()
    assert 1 in db.players(win._conn, 1)


def test_mapping_panel_grows_for_more_than_twenty_players_and_save_keeps_them(make_window):
    """Regression: only 20 rows were shown, and Save Mapping deleted the hidden players."""
    players = {i: f"Player{i}" for i in range(1, 25)}
    win = make_window(games=(), players=players)
    assert len(win.mapping_edits) >= 24
    win._save_mapping()
    assert db.players(win._conn, 1) == players


# ------------------------------------------------------------ ranking / present ----
def test_ranking_button_shows_table_and_exports_consistent_csv(make_window):
    win = make_window()
    win._show_ranking()
    shown = win.output_display.toPlainText()
    assert "Ranking" in shown and "P1" in shown and "P5" in shown
    assert "ranking.csv" in win.status_lbl.text()
    assert consistency.check_tournament_dir(win._export_dir) == []


def test_ranking_button_without_games(make_window):
    win = make_window(games=())
    win._show_ranking()
    assert "No entries to rank" in win.status_lbl.text()


def test_present_starts_the_presenter_for_this_tournament(make_window, monkeypatch):
    win = make_window()
    calls = []
    monkeypatch.setattr(T.subprocess, "Popen", lambda cmd, *a, **k: calls.append(cmd))
    win._on_present()
    cmd = calls[0]
    assert cmd[cmd.index("--db") + 1] == str(win._db_path) and cmd[cmd.index("-t") + 1] == "1"


def test_export_html_preview_is_written(make_window, tmp_path, monkeypatch):
    win = make_window()
    monkeypatch.setattr(T, "DATA_ROOT", tmp_path)
    win._on_export_html()
    assert (tmp_path / "docs" / "index.html").exists()
    assert "exported" in win.status_lbl.text()
