"""What the read-only presenter does when the database is missing, empty or out of step with the CSV files."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

pytest.importorskip("PyQt6")

import presenter  # noqa: E402
from tarock_core import csv_io, db, sync  # noqa: E402

NAMES = {i: f"P{i}" for i in range(1, 9)}


@pytest.fixture
def csv_folder(tmp_path):
    seed = db.open_rw(tmp_path / "seed.db")
    db.set_players(seed, 1, NAMES)
    db.save_game(seed, 1, 1, 1, [(1, 5), (2, -5), (3, 0), (4, 0)])
    csv_io.export_tournament(seed, 1, tmp_path / "1")
    seed.close()
    for f in tmp_path.glob("seed.db*"):
        f.unlink()
    return tmp_path


def exit_message(*args) -> str:
    with pytest.raises(SystemExit) as exc:
        presenter.open_source(*args)
    return str(exc.value)


def test_missing_database_is_an_error_that_points_to_the_entry_tool_and_creates_nothing(csv_folder):
    path = csv_folder / "tournaments.db"
    message = exit_message(path, None)
    assert "Database not found" in message and "tarockmanager.py" in message and "CSV files" in message
    assert not path.exists()                                    # the presenter never writes - not even an empty database


def test_empty_database_is_an_error_that_points_to_the_entry_tool(tmp_path):
    db.open_rw(tmp_path / "tournaments.db").close()
    assert "no tournaments" in exit_message(tmp_path / "tournaments.db", None) \
        and "tarockmanager.py" in exit_message(tmp_path / "tournaments.db", None)


def test_tournament_only_known_as_csv_files_names_the_command_to_rebuild_it(csv_folder):
    db.open_rw(csv_folder / "tournaments.db").close()
    message = exit_message(csv_folder / "tournaments.db", 1)
    assert "not in the database yet" in message and "-t 1" in message and "rebuilds the database" in message


def test_unknown_tournament_is_reported(csv_folder):
    db.open_rw(csv_folder / "tournaments.db").close()
    assert "not found" in exit_message(csv_folder / "tournaments.db", 9)


def test_open_source_returns_a_read_only_connection(csv_folder):
    conn = db.open_rw(csv_folder / "tournaments.db")
    sync.sync_tournament(conn, 1, csv_folder / "1")
    conn.close()
    ro, tournament = presenter.open_source(csv_folder / "tournaments.db", None)
    assert tournament == 1
    with pytest.raises(Exception):
        ro.execute("DELETE FROM game")


def test_csv_warning_only_when_csv_and_database_disagree(csv_folder):
    conn = db.open_rw(csv_folder / "tournaments.db")
    assert "differ from the database" in presenter.csv_warning(conn, 1, csv_folder / "1")     # database still empty
    sync.sync_tournament(conn, 1, csv_folder / "1")
    assert presenter.csv_warning(conn, 1, csv_folder / "1") is None
    assert presenter.csv_warning(conn, 1, csv_folder / "9") is None                           # no CSV folder: nothing to compare
    with open(csv_folder / "1" / "result.csv", "a") as f:
        f.write("broken\n")
    assert "cannot be used" in presenter.csv_warning(conn, 1, csv_folder / "1")


# ----------------------------------------------------------- scripts/rebuild_db.py ----
def rebuild(*args):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "rebuild_db.py"), *args],
                          capture_output=True, text=True, cwd=ROOT)


def test_rebuild_script_dry_run_changes_nothing_then_rebuilds(csv_folder):
    db_path = csv_folder / "tournaments.db"
    dry = rebuild("--db", str(db_path), "--dry-run")
    assert dry.returncode == 0 and "WOULD BE REBUILT" in dry.stdout
    done = rebuild("--db", str(db_path))
    assert done.returncode == 0 and "rebuilt from the CSV files (1 games)" in done.stdout
    again = rebuild("--db", str(db_path))
    assert "already in sync" in again.stdout
    conn = db.open_ro(db_path)
    assert len(db.games(conn, 1)) == 1 and db.players(conn, 1) == NAMES


def test_rebuild_script_reports_invalid_csv_and_exits_nonzero(csv_folder):
    with open(csv_folder / "1" / "result.csv", "a") as f:
        f.write("1,9,x,y,1,2,3\n")
    result = rebuild("--db", str(csv_folder / "tournaments.db"))
    assert result.returncode == 1 and "NOT changed" in result.stdout and "unreadable row" in result.stdout


# ------------------------------------------------------- --compare-seconds ----
def test_compare_duration_defaults_to_twenty_seconds():
    args = presenter.build_parser().parse_args([])
    assert args.compare_seconds == presenter.AUTO_COMPARE_SECONDS == 20.0


@pytest.mark.parametrize("given,expected", [("30", 30.0), ("7.5", 7.5), ("0.5", 0.5)])
def test_compare_seconds_option_is_parsed(given, expected):
    assert presenter.build_parser().parse_args(["--compare-seconds", given]).compare_seconds == expected


@pytest.mark.parametrize("bad", ["0", "-5", "abc", ""])
def test_compare_seconds_rejects_values_that_make_no_sense(bad, capsys):
    with pytest.raises(SystemExit) as exc:
        presenter.build_parser().parse_args(["--compare-seconds", bad])
    assert exc.value.code == 2
    assert "compare-seconds" in capsys.readouterr().err


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])      # kept referenced for the whole module


def test_compare_seconds_reaches_the_window_and_is_scaled_by_the_speed_option(qapp):
    from tarock_core import ranking
    from tarock_presenter.window import GraphWindow
    empty = ranking.compute([], {})
    assert GraphWindow(empty)._compare_ms == 20_000                                  # default
    assert GraphWindow(empty, compare_seconds=5)._compare_ms == 5_000
    assert GraphWindow(empty, compare_seconds=5, auto_speed=2.0)._compare_ms == 10_000   # -s multiplies it
    assert GraphWindow(empty, compare_seconds=0.001)._compare_ms == 100                  # floor shared by all stages
