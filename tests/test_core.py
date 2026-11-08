import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tarock_core import csv_io, db, ranking  # noqa: E402

NAMES = {i: f"P{i}" for i in range(1, 9)}


@pytest.fixture
def conn(tmp_path):
    c = db.open_rw(tmp_path / "t.db")
    db.set_players(c, 1, NAMES)
    return c


def g(id_, round_, seats):
    return db.Game(id_, round_, id_, tuple(seats))


# ------------------------------------------------------------- ranking ----
def test_ranking_by_total():
    s = ranking.compute([g(1, 1, [(1, 10), (2, 5), (3, -5), (4, -10)])], NAMES)
    assert [r.player for r in s.rows] == [1, 2, 3, 4]
    assert [r.rank for r in s.rows] == [1, 2, 3, 4]


def test_tiebreak_wins_then_best_round():
    # Players 1 and 2 both total 10. Player 1 won one table, player 2 none.
    games = [
        g(1, 1, [(1, 20), (3, -10), (4, -10), (5, 0)]),     # 1 wins
        g(2, 2, [(1, -10), (6, 0), (7, 10), (8, 0)]),
        g(3, 1, [(2, 6), (6, 4), (7, -5), (8, -5)]),         # 2 wins table 3 (6 top)
        g(4, 2, [(2, 4), (3, 5), (4, -4), (5, -5)]),         # 3 wins
    ]
    s = ranking.compute(games, NAMES)
    by = {r.player: r for r in s.rows}
    assert by[1].total == by[2].total == 10
    assert by[1].wins == 1 and by[2].wins == 1  # equal wins -> falls to best round
    assert by[1].best_round == 20 and by[2].best_round == 6
    assert by[1].rank == 1 and by[2].rank > by[1].rank


def test_shared_rank_is_competition_ranking():
    games = [g(1, 1, [(1, 5), (2, 5), (3, -5), (4, -5)])]
    s = ranking.compute(games, NAMES)
    assert [(r.player, r.rank, r.tied) for r in s.rows] == [
        (1, 1, True), (2, 1, True), (3, 3, True), (4, 3, True)]


def test_ranking_independent_of_input_order():
    games = [g(1, 1, [(1, 5), (2, 5), (3, -5), (4, -5)]),
             g(2, 2, [(5, 7), (6, -7), (7, 0), (8, 0)])]
    a = ranking.compute(games, NAMES)
    b = ranking.compute(list(reversed(games)), NAMES)
    assert [(r.player, r.rank) for r in a.rows] == [(r.player, r.rank) for r in b.rows]


def test_numeric_not_string_order():
    names = {2: "B", 10: "A"}
    s = ranking.compute([g(1, 1, [(2, 1), (10, -1), (3, 0), (4, 0)])], {**names, 3: "C", 4: "D"})
    assert s.rows[0].player == 2


# ---------------------------------------------------------- validation ----
def seats(*pts, players=(1, 2, 3, 4)):
    return list(zip(players, pts))


def test_save_and_load_roundtrip(conn):
    gid = db.save_game(conn, 1, 1, 1, seats(10, -5, -5, 0))
    (game,) = db.games(conn, 1)
    assert game.id == gid and game.seats == ((1, 10), (2, -5), (3, -5), (4, 0))
    assert db.check(conn, 1) == []


@pytest.mark.parametrize("pts,players,msg", [
    ((1, 1, 1, 1), (1, 2, 3, 4), "sum to 0"),
    ((0, 0, 0, 0), (1, 1, 3, 4), "unique"),
    ((0, 0, 0, 0), (1, 2, 3, 99), "Unknown player"),
])
def test_rejects_bad_games(conn, pts, players, msg):
    with pytest.raises(db.ValidationError, match=msg):
        db.save_game(conn, 1, 1, 1, seats(*pts, players=players))
    assert db.games(conn, 1) == []


def test_rejects_duplicate_table_and_double_booking(conn):
    db.save_game(conn, 1, 1, 1, seats(0, 0, 0, 0))
    with pytest.raises(db.ValidationError, match="already has a result"):
        db.save_game(conn, 1, 1, 1, seats(0, 0, 0, 0, players=(5, 6, 7, 8)))
    with pytest.raises(db.ValidationError, match="already played in round 1"):
        db.save_game(conn, 1, 1, 2, seats(0, 0, 0, 0, players=(4, 5, 6, 7)))
    db.save_game(conn, 1, 2, 1, seats(0, 0, 0, 0, players=(4, 5, 6, 7)))  # other round is fine


def test_change_game_keeps_id_and_allows_own_slot(conn):
    gid = db.save_game(conn, 1, 1, 1, seats(1, -1, 0, 0))
    db.save_game(conn, 1, 1, 1, seats(2, -2, 0, 0), game_id=gid)
    (game,) = db.games(conn, 1)
    assert game.id == gid and game.seats[0] == (1, 2)


def test_failed_change_leaves_old_data(conn):
    gid = db.save_game(conn, 1, 1, 1, seats(1, -1, 0, 0))
    with pytest.raises(db.ValidationError):
        db.save_game(conn, 1, 1, 1, seats(5, 5, 5, 5), game_id=gid)
    assert db.games(conn, 1)[0].seats[0] == (1, 1)


def test_cannot_remove_player_with_results(conn):
    db.save_game(conn, 1, 1, 1, seats(0, 0, 0, 0))
    with pytest.raises(db.ValidationError, match="already has results"):
        db.set_players(conn, 1, {k: v for k, v in NAMES.items() if k != 1})
    assert 1 in db.players(conn, 1)


def test_schema_blocks_bad_data_even_without_app_checks(conn):
    db.save_game(conn, 1, 1, 1, seats(0, 0, 0, 0))
    gid = db.games(conn, 1)[0].id
    with pytest.raises(sqlite3.IntegrityError):  # unknown player
        conn.execute("INSERT INTO result VALUES (?,?,?,?,?,?)", (gid, 1, 1, 1, 99, 0))
    with pytest.raises(sqlite3.IntegrityError):  # same player twice in a round
        conn.execute("INSERT INTO game(tournament, round, table_no) VALUES (1,1,9)")
        conn.execute("INSERT INTO result VALUES (last_insert_rowid(),1,1,1,1,0)")


def test_swap_names(conn):
    db.set_players(conn, 1, {**NAMES, 1: "P2", 2: "P1"})
    assert db.players(conn, 1)[1] == "P2"


def test_check_detects_corruption(conn):
    db.save_game(conn, 1, 1, 1, seats(0, 0, 0, 0))
    conn.execute("UPDATE result SET points = 5 WHERE seat = 1")
    conn.commit()
    assert any("sum to" in p for p in db.check(conn, 1))


# ------------------------------------------------------------ read-only ----
def test_readonly_connection_cannot_write(conn, tmp_path):
    db.save_game(conn, 1, 1, 1, seats(0, 0, 0, 0))
    ro = db.open_ro(tmp_path / "t.db")
    assert len(db.games(ro, 1)) == 1
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("DELETE FROM game")
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("INSERT INTO tournament(number) VALUES (5)")


# ----------------------------------------------------------------- csv ----
def test_csv_export_import_roundtrip(conn, tmp_path):
    db.set_players(conn, 1, {**NAMES, 4: "Roland, Gerald"})  # comma in a name
    db.save_game(conn, 1, 1, 1, seats(10, -5, -5, 0))
    out = tmp_path / "1"
    csv_io.export_tournament(conn, 1, out)
    assert "Roland, Gerald" in (out / "ranking.csv").read_text()

    other = db.open_rw(tmp_path / "other.db")
    assert csv_io.import_tournament(other, 1, out) == 1
    assert db.games(other, 1)[0].seats == db.games(conn, 1)[0].seats
    assert db.players(other, 1)[4] == "Roland, Gerald"


def test_import_reports_all_bad_rows_and_stores_nothing(tmp_path):
    d = tmp_path / "7"
    d.mkdir()
    (d / "player_numbers.csv").write_text("Player_Number,Player_Name\n1,A\n2,B\n3,C\n4,D\n")
    (d / "result.csv").write_text(
        "Table,Round,Player_Number1,Points1,Player_Number2,Points2,Player_Number3,Points3,Player_Number4,Points4\n"
        "1,1,1,5,2,5,3,5,4,5\n"      # bad sum
        "2,1,1,0,2,0,3,0,x,0\n"      # unreadable
    )
    c = db.open_rw(tmp_path / "i.db")
    with pytest.raises(csv_io.ImportErrors) as e:
        csv_io.import_tournament(c, 7, d)
    assert len(e.value.errors) == 1 or len(e.value.errors) == 2
    assert db.tournaments(c) == []


def test_readonly_reader_sees_data_version_change(conn, tmp_path):
    """The presentation's live update relies on this signal from another connection's commits."""
    ro = db.open_ro(tmp_path / "t.db")
    before = ro.execute("PRAGMA data_version").fetchone()[0]
    assert ro.execute("PRAGMA data_version").fetchone()[0] == before  # idle: unchanged
    db.save_game(conn, 1, 1, 1, seats(0, 0, 0, 0))
    assert ro.execute("PRAGMA data_version").fetchone()[0] != before
    assert len(db.games(ro, 1)) == 1


# ----------------------------------------------------- limits and messages ----
def test_points_limit_is_validated_with_a_friendly_message(conn):
    db.save_game(conn, 1, 1, 1, seats(1000, -1000, 0, 0))                    # the limit itself is fine
    with pytest.raises(db.ValidationError, match="between -1000 and 1000"):
        db.save_game(conn, 1, 2, 1, seats(1001, -1001, 0, 0))
    assert len(db.games(conn, 1)) == 1


def test_duplicate_table_message_does_not_mention_a_removed_button(conn):
    db.save_game(conn, 1, 1, 1, seats(0, 0, 0, 0))
    with pytest.raises(db.ValidationError) as exc:
        db.save_game(conn, 1, 1, 1, seats(0, 0, 0, 0, players=(5, 6, 7, 8)))
    assert "already has a result" in str(exc.value) and "Change" not in str(exc.value)
