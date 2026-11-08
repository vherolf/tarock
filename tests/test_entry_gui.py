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


# ---------------------------------------------- CSV files are the master copy ----
@pytest.fixture
def failing_export(monkeypatch):
    """Switchable disk failure for the CSV export. Starts working; set state['fail'] = True to break it."""
    state = {"fail": False}
    real = T.csv_io.export_tournament

    def export(*args, **kwargs):
        if state["fail"]:
            raise OSError("disk full")
        return real(*args, **kwargs)

    monkeypatch.setattr(T.csv_io, "export_tournament", export)
    return state


def csv_snapshot(win):
    return {p.name: p.read_bytes() for p in win._export_dir.iterdir()}


def test_failed_csv_write_means_nothing_is_saved(make_window, failing_export):
    win = make_window()
    before, files = stored(win), csv_snapshot(win)
    failing_export["fail"] = True
    fill(win, [1, 2, 3, 4], [0, 0, 0, 0], round_=2, table=1)
    win._on_submit()
    assert "NOT saved" in win.status_lbl.text() and "disk full" in win.status_lbl.text()
    assert "red" in win.status_lbl.styleSheet()
    assert stored(win) == before and len(win.games) == 2           # database rolled back, view unchanged
    assert csv_snapshot(win) == files                              # CSV files untouched, no temp files left behind


def test_every_save_path_is_all_or_nothing(make_window, failing_export):
    win = make_window()
    before, files = stored(win), csv_snapshot(win)
    failing_export["fail"] = True
    free = next(i for i, (n, _) in enumerate(win.mapping_edits) if not n.text())
    win.mapping_edits[free][0].setText("9")
    win.mapping_edits[free][1].setText("Newcomer")
    win._save_mapping()
    assert "NOT saved" in win.status_lbl.text() and 9 not in db.players(win._conn, 1)
    win._delete_current()
    assert "NOT saved" in win.status_lbl.text() and stored(win) == before
    assert csv_snapshot(win) == files


def test_saving_works_again_once_the_disk_problem_is_gone(make_window, failing_export):
    win = make_window()
    failing_export["fail"] = True
    fill(win, [1, 2, 3, 4], [0, 0, 0, 0], round_=2, table=1)
    win._on_submit()
    failing_export["fail"] = False
    win._on_submit()                                               # same input again
    assert "Saved round 2, table 1" in win.status_lbl.text() and len(stored(win)) == 3
    assert consistency.check_tournament_dir(win._export_dir) == []


def test_ranking_button_and_html_preview_report_a_failed_csv_write(make_window, failing_export, tmp_path, monkeypatch):
    win = make_window()
    failing_export["fail"] = True
    win._show_ranking()
    assert "could not be written" in win.status_lbl.text() and "Ranking" in win.output_display.toPlainText()
    monkeypatch.setattr(T, "DATA_ROOT", tmp_path)
    win._on_export_html()
    assert not (tmp_path / "docs" / "index.html").exists()         # never built from stale CSV files
    assert "not exported" in win.status_lbl.text() and "disk full" in win.status_lbl.text()


# ----------------------------------------------------------- start-up sync ----
@pytest.fixture
def csv_folder(tmp_path):
    """tournaments/ with tournament 1's CSV files (2 games, 8 players) and NO database."""
    seed = db.open_rw(tmp_path / "seed.db")
    db.set_players(seed, 1, NAMES)
    db.save_game(seed, 1, 1, 1, [(1, 5), (2, -5), (3, 0), (4, 0)])
    db.save_game(seed, 1, 1, 2, [(5, 3), (6, -3), (7, 0), (8, 0)])
    from tarock_core import csv_io
    csv_io.export_tournament(seed, 1, tmp_path / "1")
    seed.close()
    for f in tmp_path.glob("seed.db*"):
        f.unlink()
    return tmp_path


def test_deleted_database_is_rebuilt_on_start_and_saving_keeps_every_csv_game(app, csv_folder, dialogs):
    """The motivating scenario: delete the database, restart. Used to ignore the CSVs and then overwrite them."""
    before = {p.name: p.read_bytes() for p in (csv_folder / "1").iterdir()}
    win = T.MainWindow(csv_folder / "tournaments.db", 1)
    assert len(win.games) == 2 and len(win.mapping) == 8                       # the data is back
    assert "rebuilt from the CSV files (2 games)" in win.status_lbl.text()
    assert not [d for d in dialogs.shown if d[0] == "warning"]                 # nothing was replaced: no scary dialog
    win._save_mapping()                                                        # a save used to wipe the CSV files...
    fill(win, [1, 2, 3, 4], [4, -4, 0, 0], round_=2, table=1)
    win._on_submit()
    rows = (csv_folder / "1" / "result.csv").read_text().strip().splitlines()
    assert len(rows) == 1 + 3                                                  # ...now: header + the 2 old games + the new one
    assert rows[1:3] == before["result.csv"].decode().strip().splitlines()[1:]
    win.close()


def test_different_database_content_is_replaced_by_the_csv_files_after_a_backup(app, csv_folder, dialogs):
    conn = db.open_rw(csv_folder / "tournaments.db")
    db.set_players(conn, 1, {i: f"Other{i}" for i in range(1, 9)})
    db.save_game(conn, 1, 7, 1, [(1, 9), (2, -9), (3, 0), (4, 0)])
    conn.close()
    win = T.MainWindow(csv_folder / "tournaments.db", 1)
    assert win.mapping == NAMES and len(win.games) == 2                        # CSV wins
    warning = next(d for d in dialogs.shown if d[0] == "warning")
    backups = list((csv_folder / "backups").glob("tournaments-*.db"))
    assert len(backups) == 1 and str(backups[0]) in warning[1]                 # the dialog says where the old database went
    assert "master copy" in warning[1]
    win.close()


def test_unusable_csv_files_stop_the_start_and_change_nothing(app, csv_folder):
    with open(csv_folder / "1" / "result.csv", "a") as f:
        f.write("1,9,x,y,1,2,3\n")
    before = {p.name: p.read_bytes() for p in (csv_folder / "1").iterdir()}
    with pytest.raises(T.StartupError) as exc:
        T.MainWindow(csv_folder / "tournaments.db", 1)
    assert "line 4" in exc.value.message and "master copy" in exc.value.message
    assert {p.name: p.read_bytes() for p in (csv_folder / "1").iterdir()} == before
    conn = db.open_rw(csv_folder / "tournaments.db")
    assert db.games(conn, 1) == [] and db.players(conn, 1) == {}               # database untouched too
    conn.close()


def test_half_present_csv_set_stops_the_start(app, csv_folder):
    (csv_folder / "1" / "player_numbers.csv").unlink()
    with pytest.raises(T.StartupError) as exc:
        T.MainWindow(csv_folder / "tournaments.db", 1)
    assert "player_numbers.csv is missing" in exc.value.message
    assert (csv_folder / "1" / "result.csv").exists()                          # the survivor is not overwritten


def test_database_without_csv_files_gets_them_on_start(app, tmp_path, dialogs):
    path = tmp_path / "tournaments.db"
    conn = db.open_rw(path)
    db.set_players(conn, 1, NAMES)
    db.save_game(conn, 1, 1, 1, [(1, 5), (2, -5), (3, 0), (4, 0)])
    conn.close()
    win = T.MainWindow(path, 1)
    assert (tmp_path / "1" / "result.csv").exists() and "CSV files created" in win.status_lbl.text()
    assert consistency.check_tournament_dir(tmp_path / "1") == []
    win.close()


def test_stale_ranking_csv_is_regenerated_on_start(app, csv_folder, dialogs):
    (csv_folder / "1" / "ranking.csv").write_text("Rank,Player_Number,Player_Name,Total_Points\n1,1,Old,1\n")
    win = T.MainWindow(csv_folder / "tournaments.db", 1)
    assert "ranking.csv was out of date" in win.status_lbl.text()
    assert consistency.check_tournament_dir(csv_folder / "1") == []
    win.close()


def test_csv_folder_that_cannot_be_written_at_start_is_a_warning(app, tmp_path, dialogs, failing_export):
    path = tmp_path / "tournaments.db"
    conn = db.open_rw(path)
    db.set_players(conn, 1, NAMES)
    conn.close()
    failing_export["fail"] = True
    win = T.MainWindow(path, 1)                                                # opens, but says so
    assert "WARNING" in win.status_lbl.text() and "disk full" in win.status_lbl.text()
    win.close()


def test_default_tournament_also_considers_csv_only_folders(app, csv_folder):
    (csv_folder / "5").mkdir()
    for name in ("result.csv", "player_numbers.csv"):
        (csv_folder / "5" / name).write_text("x\n")
    assert T.default_tournament(csv_folder / "tournaments.db") == 5            # no database yet, CSV folders decide
    conn = db.open_rw(csv_folder / "tournaments.db")
    db.ensure_tournament(conn, 9)
    conn.close()
    assert T.default_tournament(csv_folder / "tournaments.db") == 9            # the database may know a newer one


def test_default_tournament_without_anything_is_one(app, tmp_path):
    assert T.default_tournament(tmp_path / "tournaments.db") == 1


# ------------------------------------------------------------------ points limit ----
def test_points_fields_accept_up_to_the_database_limit(make_window):
    win = make_window()
    assert all(b.minimum() == -db.MAX_POINTS and b.maximum() == db.MAX_POINTS for b in win.points_spins)
    assert db.MAX_POINTS == 1000
    fill(win, [1, 2, 3, 4], [300, -100, -100, -100], round_=2, table=1)        # a winner above the old +100 limit
    win._on_submit()
    assert stored(win)[-1].seats[0] == (1, 300)
    fill(win, [5, 6, 7, 8], [1000, -1000, 0, 0], round_=2, table=2)
    win._on_submit()
    assert stored(win)[-1].seats[:2] == ((5, 1000), (6, -1000))
    assert consistency.check_tournament_dir(win._export_dir) == []
