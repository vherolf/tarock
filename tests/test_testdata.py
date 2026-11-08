"""The throw-away test tournaments 0 (14 players) and 1 (16 players) generated at every start."""
import random
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tarock_core import consistency, csv_io, db, testdata  # noqa: E402


def gen(n_players, seed=1, rounds=6):
    return testdata.generate(n_players, rounds, random.Random(seed))


# ------------------------------------------------------------------ generation ----
@pytest.mark.parametrize("n_players,tables", [(14, 3), (16, 4), (8, 2), (4, 1)])
def test_generated_tournament_has_the_expected_shape(n_players, tables):
    t = gen(n_players)
    assert len(t.players) == n_players and len(set(t.players.values())) == n_players   # unique names
    assert len(t.games) == tables * 6
    for rnd in range(1, 7):
        in_round = [g for g in t.games if g.round == rnd]
        assert sorted(g.table for g in in_round) == list(range(1, tables + 1))
        seated = [p for g in in_round for p, _ in g.seats]
        assert len(seated) == len(set(seated)) == tables * 4                            # nobody plays twice a round


@pytest.mark.parametrize("seed", range(20))
def test_every_table_sums_to_zero_and_scores_stay_plausible(seed):
    for n in (14, 16):
        for g in gen(n, seed).games:
            assert sum(points for _, points in g.seats) == 0
            assert all(abs(points) <= 40 for _, points in g.seats)


def test_sitting_out_is_spread_evenly():
    t = gen(14)                                       # 2 players sit out per round, 6 rounds = 12 different players
    played = {p: sum(1 for g in t.games for q, _ in g.seats if q == p) for p in t.players}
    assert set(played.values()) <= {5, 6} and sum(1 for v in played.values() if v == 5) == 12


def test_sixteen_players_never_sit_out():
    t = gen(16)
    assert all(sum(1 for g in t.games for q, _ in g.seats if q == p) == 6 for p in t.players)


def test_same_seed_same_data_different_seed_different_data():
    assert gen(14, 5) == gen(14, 5)
    assert gen(14, 5) != gen(14, 6)


@pytest.mark.parametrize("bad", [3, 0, 21])
def test_unsupported_player_counts_are_rejected(bad):
    with pytest.raises(ValueError):
        gen(bad)


# --------------------------------------------------------------------- refresh ----
@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "tournaments.db"


def test_refresh_creates_both_tournaments_in_the_database_and_as_csv_files(db_path):
    seed = testdata.refresh(db_path, seed=42)
    assert seed == 42
    conn = db.open_ro(db_path)
    assert {t: (len(db.players(conn, t)), len(db.games(conn, t))) for t in (0, 1)} == {0: (14, 18), 1: (16, 24)}
    for number in (0, 1):
        assert consistency.check_tournament_dir(db_path.parent / str(number)) == []
        assert db.check(conn, number) == []
    assert not (db_path.parent / "backups").exists()      # throw-away data: no backups


def test_refresh_without_a_seed_picks_a_new_one_each_time(db_path):
    seeds = {testdata.refresh(db_path) for _ in range(5)}
    assert len(seeds) > 1


def test_refresh_replaces_whatever_was_there_so_testing_always_starts_clean(db_path):
    testdata.refresh(db_path, seed=7)
    conn = db.open_rw(db_path)
    fresh = [(g.round, g.table, g.seats) for g in db.games(conn, 0)]
    db.delete_game(conn, db.games(conn, 0)[0].id)                                       # "testing": delete games ...
    db.save_game(conn, 1, 9, 1, [(1, 1), (2, -1), (3, 0), (4, 0)])                      # ... and add one
    conn.close()
    with open(db_path.parent / "0" / "result.csv", "a") as f:                           # even edit a CSV by hand
        f.write("not,even,valid\n")
    testdata.refresh(db_path, seed=7)
    conn = db.open_ro(db_path)
    assert [(g.round, g.table, g.seats) for g in db.games(conn, 0)] == fresh
    assert len(db.games(conn, 1)) == 24
    assert consistency.check_tournament_dir(db_path.parent / "0") == []


def test_refresh_with_different_seeds_gives_different_data(db_path):
    testdata.refresh(db_path, seed=1)
    first = (db_path.parent / "1" / "result.csv").read_text()
    testdata.refresh(db_path, seed=2)
    assert (db_path.parent / "1" / "result.csv").read_text() != first


def test_the_two_tournaments_are_independent_and_reproducible_from_one_seed(db_path, tmp_path):
    testdata.refresh(db_path, seed=100)
    other = tmp_path / "other" / "tournaments.db"
    testdata.refresh(other, seed=100)
    for number in (0, 1):
        assert (db_path.parent / str(number) / "result.csv").read_bytes() == (other.parent / str(number) / "result.csv").read_bytes()
    assert (db_path.parent / "0" / "result.csv").read_bytes() != (db_path.parent / "1" / "result.csv").read_bytes()


def test_refresh_leaves_other_tournaments_alone(db_path):
    conn = db.open_rw(db_path)
    db.set_players(conn, 17, {i: f"P{i}" for i in range(1, 9)})
    db.save_game(conn, 17, 1, 1, [(1, 5), (2, -5), (3, 0), (4, 0)])
    csv_io.export_tournament(conn, 17, db_path.parent / "17")
    before = {p.name: p.read_bytes() for p in (db_path.parent / "17").iterdir()}
    conn.close()
    testdata.refresh(db_path, seed=3)
    conn = db.open_ro(db_path)
    assert len(db.games(conn, 17)) == 1 and db.players(conn, 17)[1] == "P1"
    assert {p.name: p.read_bytes() for p in (db_path.parent / "17").iterdir()} == before


def test_refresh_works_when_the_database_was_deleted(db_path):
    testdata.refresh(db_path, seed=9)
    for f in db_path.parent.glob("tournaments.db*"):
        f.unlink()                                                                       # the "delete the db" experiment
    testdata.refresh(db_path, seed=9)
    assert len(db.games(db.open_ro(db_path), 1)) == 24


def test_a_tournament_database_written_by_refresh_is_a_valid_sqlite_file(db_path):
    testdata.refresh(db_path, seed=1)
    assert sqlite3.connect(db_path).execute("PRAGMA integrity_check").fetchone()[0] == "ok"


# ------------------------------------------------------ entry tool command line ----
@pytest.fixture(scope="module")
def entry():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PyQt6")
    import tarockmanager
    return tarockmanager


def test_entry_tool_regenerates_test_data_by_default(entry, db_path):
    args = entry.build_parser().parse_args(["--db", str(db_path)])
    message = entry.refresh_test_data(args)
    assert "regenerated" in message and "seed" in message
    assert (db_path.parent / "0" / "result.csv").exists() and (db_path.parent / "1" / "result.csv").exists()


def test_no_test_data_flag_skips_it(entry, db_path):
    args = entry.build_parser().parse_args(["--db", str(db_path), "--no-test-data"])
    assert entry.refresh_test_data(args) is None
    assert not (db_path.parent / "0").exists() and not db_path.exists()


def test_test_seed_flag_makes_it_reproducible(entry, db_path, tmp_path):
    a = entry.build_parser().parse_args(["--db", str(db_path), "--test-seed", "77"])
    assert "seed 77" in entry.refresh_test_data(a)
    first = (db_path.parent / "1" / "result.csv").read_bytes()
    b = entry.build_parser().parse_args(["--db", str(tmp_path / "x" / "tournaments.db"), "--test-seed", "77"])
    entry.refresh_test_data(b)
    assert (tmp_path / "x" / "1" / "result.csv").read_bytes() == first


@pytest.fixture(scope="module")
def qapp(entry):
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])      # kept referenced for the whole module


def test_window_shows_the_regeneration_notice(entry, qapp, db_path):
    args = entry.build_parser().parse_args(["--db", str(db_path), "--test-seed", "5"])
    notice = entry.refresh_test_data(args)
    win = entry.MainWindow(db_path, 0, notice)
    assert "regenerated (seed 5)" in win.status_lbl.text()
    assert len(win.games) == 18 and len(win.mapping) == 14
    win.close()
    win = entry.MainWindow(db_path, 1, notice)
    assert len(win.games) == 24 and len(win.mapping) == 16
    win.close()


def test_default_tournament_is_not_a_test_tournament_when_a_real_one_exists(entry, db_path):
    testdata.refresh(db_path, seed=1)
    conn = db.open_rw(db_path)
    db.ensure_tournament(conn, 17)
    conn.close()
    assert entry.default_tournament(db_path) == 17
