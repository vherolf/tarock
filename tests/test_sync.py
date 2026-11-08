"""CSV files are the master copy; the database is rebuilt from them (tarock_core/sync.py)."""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tarock_core import consistency, csv_io, db, ranking, sync  # noqa: E402

NAMES = {i: f"P{i}" for i in range(1, 9)}
GAMES = [
    (1, 1, [(1, 10), (2, -4), (3, -6), (4, 0)]),
    (1, 2, [(5, 7), (6, -7), (7, 0), (8, 0)]),
    (2, 1, [(1, -3), (5, 8), (3, -2), (6, -3)]),
]


def fill(conn, tournament=1, games=GAMES, names=NAMES):
    db.set_players(conn, tournament, names)
    for round_, table, seats in games:
        db.save_game(conn, tournament, round_, table, seats)


@pytest.fixture
def base(tmp_path):
    """tournaments/ folder with CSV files for tournament 1 (3 games) and no database yet."""
    seed = db.open_rw(tmp_path / "seed.db")
    fill(seed)
    csv_io.export_tournament(seed, 1, tmp_path / "1")
    seed.close()
    (tmp_path / "seed.db").unlink()
    for ext in ("-wal", "-shm"):
        (tmp_path / f"seed.db{ext}").unlink(missing_ok=True)
    return tmp_path


@pytest.fixture
def conn(base):
    connection = db.open_rw(base / "tournaments.db")
    yield connection
    connection.close()


def state(conn, tournament=1):
    return db.players(conn, tournament), [(g.round, g.table, g.seats) for g in db.games(conn, tournament)]


def run(conn, base, tournament=1):
    return sync.sync_tournament(conn, tournament, base / str(tournament), base / "backups")


# --------------------------------------------------- deleted / empty database ----
def test_deleted_database_is_rebuilt_from_the_csv_files(base, conn):
    """The scenario that motivated all this: no database, CSV files present."""
    result = run(conn, base)
    assert result.action == "rebuilt" and result.games == 3 and not result.replaced_data
    assert result.backup is None                                   # nothing existed that could be lost
    players, games = state(conn)
    assert players == NAMES and len(games) == 3
    assert db.check(conn, 1) == []


def test_rebuild_keeps_game_order_and_values(base, conn):
    run(conn, base)
    assert [(r, t) for r, t, _ in state(conn)[1]] == [(1, 1), (1, 2), (2, 1)]
    assert state(conn)[1][0][2] == ((1, 10), (2, -4), (3, -6), (4, 0))


def test_in_sync_database_is_not_written_at_all(base, conn):
    run(conn, base)
    before = conn.total_changes
    version = conn.execute("PRAGMA data_version").fetchone()[0]
    result = run(conn, base)
    assert result.action == "in_sync" and not result.replaced_data
    assert conn.total_changes == before                            # no write -> the presenter is not disturbed
    assert conn.execute("PRAGMA data_version").fetchone()[0] == version
    assert not (base / "backups").exists()


def test_rebuild_leaves_the_csv_data_files_byte_for_byte_untouched(base, conn):
    before = {name: (base / "1" / name).read_bytes() for name in (csv_io.RESULT_FILE, csv_io.PLAYERS_FILE)}
    run(conn, base)
    after = {name: (base / "1" / name).read_bytes() for name in before}
    assert before == after


# ------------------------------------------------------- database differs ----
def test_csv_wins_over_different_database_content_and_a_backup_is_made(base, conn):
    fill(conn, games=GAMES[:1], names={i: f"Other{i}" for i in range(1, 9)})   # the database says something else
    result = run(conn, base)
    assert result.action == "rebuilt" and result.replaced_data
    assert state(conn)[0] == NAMES and len(state(conn)[1]) == 3                 # the CSV content is now in the database
    assert result.backup is not None and result.backup.exists()
    old = sqlite3.connect(result.backup)                                        # ...and the old content is in the backup
    assert old.execute("SELECT count(*) FROM game").fetchone()[0] == 1
    assert old.execute("SELECT name FROM player WHERE number = 1").fetchone()[0] == "Other1"
    old.close()


def test_a_game_only_in_the_database_is_replaced_but_backed_up(base, conn):
    run(conn, base)
    db.save_game(conn, 1, 3, 1, [(1, 1), (2, -1), (3, 0), (4, 0)])             # change that never reached the CSV
    result = run(conn, base)
    assert len(state(conn)[1]) == 3 and result.replaced_data and result.backup
    assert sqlite3.connect(result.backup).execute("SELECT count(*) FROM game").fetchone()[0] == 4


def test_only_the_synced_tournament_is_touched(base, conn):
    fill(conn, tournament=2, games=GAMES[:1])
    run(conn, base)
    assert len(db.games(conn, 2)) == 1 and len(db.players(conn, 2)) == 8


def test_old_backups_are_pruned(base, conn):
    backups = base / "backups"
    backups.mkdir()
    for i in range(sync.MAX_BACKUPS + 5):
        (backups / f"tournaments-20200101-0000{i:02d}-t1.db").write_bytes(b"x")
    fill(conn, games=GAMES[:1])
    run(conn, base)
    files = sorted(backups.glob("tournaments-*.db"))
    assert len(files) == sync.MAX_BACKUPS
    assert not (backups / "tournaments-20200101-000000-t1.db").exists()         # the oldest went first


# ------------------------------------------------------------ bad CSV files ----
def test_unreadable_csv_changes_nothing_and_lists_the_rows(base, conn):
    run(conn, base)
    with open(base / "1" / "result.csv", "a") as f:
        f.write("1,9,x,y,1,2,3\n")
    result = run(conn, base)
    assert result.action == "invalid" and any("line 5" in e for e in result.errors)
    assert len(state(conn)[1]) == 3 and not (base / "backups").exists()


def test_rule_breaking_csv_changes_nothing(base, conn):
    run(conn, base)
    lines = (base / "1" / "result.csv").read_text().splitlines()
    lines[1] = "1,1,1,10,2,-4,3,-6,4,5"                                      # points no longer sum to 0
    (base / "1" / "result.csv").write_text("\n".join(lines) + "\n")
    result = run(conn, base)
    assert result.action == "invalid" and any("sum to 0" in e for e in result.errors)
    assert state(conn)[1][0][2] == ((1, 10), (2, -4), (3, -6), (4, 0))          # database untouched
    assert not (base / "backups").exists()


def test_unknown_player_in_csv_is_rejected(base, conn):
    (base / "1" / "player_numbers.csv").write_text("Player_Number,Player_Name\n1,Only\n")
    assert run(conn, base).action == "invalid"


@pytest.mark.parametrize("missing,survivor", [("player_numbers.csv", "result.csv"), ("result.csv", "player_numbers.csv")])
def test_half_present_csv_set_is_refused_so_the_survivor_is_not_overwritten(base, conn, missing, survivor):
    (base / "1" / missing).unlink()
    result = run(conn, base)
    assert result.action == "invalid" and missing in result.errors[0] and survivor in result.errors[0]
    assert sync.check(conn, 1, base / "1")[0] == "invalid"
    assert (base / "1" / survivor).exists() and state(conn) == ({}, [])


# ------------------------------------------------------------- no CSV yet ----
def test_database_without_csv_files_exports_them(tmp_path):
    conn = db.open_rw(tmp_path / "tournaments.db")
    fill(conn)
    result = sync.sync_tournament(conn, 1, tmp_path / "1", tmp_path / "backups")
    assert result.action == "exported" and result.games == 3
    assert consistency.check_tournament_dir(tmp_path / "1") == []


def test_nothing_anywhere_is_fine(tmp_path):
    conn = db.open_rw(tmp_path / "tournaments.db")
    assert sync.sync_tournament(conn, 7, tmp_path / "7").action == "nothing"


def test_export_failure_at_startup_is_a_warning_not_a_crash(tmp_path, monkeypatch):
    conn = db.open_rw(tmp_path / "tournaments.db")
    fill(conn)
    monkeypatch.setattr(csv_io, "export_tournament", lambda *a, **k: (_ for _ in ()).throw(OSError("read-only")))
    result = sync.sync_tournament(conn, 1, tmp_path / "1")
    assert result.action == "exported" and "read-only" in result.warnings[0]


# --------------------------------------------------- derived ranking.csv ----
def test_stale_ranking_csv_is_regenerated_without_touching_the_data(base, conn):
    run(conn, base)
    (base / "1" / "ranking.csv").write_text("Rank,Player_Number,Player_Name,Total_Points\n1,1,Hacked,999\n")
    data_before = (base / "1" / "result.csv").read_bytes()
    result = run(conn, base)
    assert result.action == "in_sync" and result.ranking_refreshed
    assert (base / "1" / "result.csv").read_bytes() == data_before
    assert consistency.check_tournament_dir(base / "1") == []


def test_missing_ranking_csv_is_recreated(base, conn):
    (base / "1" / "ranking.csv").unlink()
    result = run(conn, base)
    assert result.ranking_refreshed and (base / "1" / "ranking.csv").exists()


# ------------------------------------------------------------- read-only check ----
def test_check_reports_each_state_without_writing(base, conn):
    csv_dir = base / "1"
    assert sync.check(conn, 1, csv_dir)[0] == "differs"                        # database empty, CSV has data
    run(conn, base)
    changes = conn.total_changes
    assert sync.check(conn, 1, csv_dir)[0] == "in_sync"
    assert sync.check(conn, 1, base / "9")[0] == "no_csv"
    db.save_game(conn, 1, 3, 1, [(1, 1), (2, -1), (3, 0), (4, 0)])
    assert sync.check(conn, 1, csv_dir)[0] == "differs"
    with open(csv_dir / "result.csv", "a") as f:
        f.write("oops\n")
    status, errors = sync.check(conn, 1, csv_dir)
    assert status == "invalid" and errors
    assert conn.total_changes == changes + 1 + 4                                # only my own save_game wrote


def test_check_works_on_a_read_only_connection(base, conn):
    run(conn, base)
    ro = db.open_ro(base / "tournaments.db")
    assert sync.check(ro, 1, base / "1")[0] == "in_sync"


# ---------------------------------------------------------- discovery ----
def test_available_tournaments_include_csv_only_folders(base, conn):
    fill(conn, tournament=5, games=GAMES[:1])
    (base / "notes").mkdir()
    (base / "12").mkdir()                                                       # a folder without CSV data: ignored
    assert sync.available_tournaments(conn, base) == [1, 5]
    assert sync.csv_tournament_numbers(base) == [1]


# ------------------------------------------------- atomic CSV export / transaction ----
def test_export_is_all_or_nothing(base, conn, monkeypatch):
    run(conn, base)
    before = {p.name: p.read_bytes() for p in (base / "1").iterdir()}
    db.save_game(conn, 1, 3, 1, [(1, 1), (2, -1), (3, 0), (4, 0)])
    real, calls = csv_io._write_temp, []

    def flaky(path, rows):
        calls.append(path.name)
        if len(calls) == 3:                                                    # the third file cannot be written
            raise OSError("disk full")
        return real(path, rows)

    monkeypatch.setattr(csv_io, "_write_temp", flaky)
    with pytest.raises(OSError):
        csv_io.export_tournament(conn, 1, base / "1")
    assert {p.name: p.read_bytes() for p in (base / "1").iterdir()} == before   # no file changed, no temp file left


def test_transaction_rolls_everything_back_on_error(conn):
    fill(conn, games=GAMES[:1])
    with pytest.raises(RuntimeError):
        with db.transaction(conn):
            db.save_game(conn, 1, 5, 1, [(1, 1), (2, -1), (3, 0), (4, 0)])
            db.set_players(conn, 1, {**NAMES, 9: "New"})
            raise RuntimeError("export failed")
    assert len(db.games(conn, 1)) == 1 and 9 not in db.players(conn, 1)
    assert not conn.in_transaction


def test_transaction_commits_all_writes_together(conn):
    with db.transaction(conn):
        db.set_players(conn, 1, NAMES)
        db.save_game(conn, 1, 1, 1, [(1, 1), (2, -1), (3, 0), (4, 0)])
        assert conn.in_transaction                                              # nothing committed yet
    assert not conn.in_transaction and len(db.games(conn, 1)) == 1


def test_transactions_cannot_be_nested(conn):
    with db.transaction(conn):
        with pytest.raises(RuntimeError):
            with db.transaction(conn):
                pass


def test_rebuilt_ranking_matches_the_rule_based_ranking(base, conn):
    run(conn, base)
    standings = ranking.compute(db.games(conn, 1), db.players(conn, 1))
    assert [s.player for s in standings.rows][0] == 5                           # 15 points: 7 + 8
