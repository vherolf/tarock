import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tarock_core import db, html_views, ranking  # noqa: E402

NAMES = {1: "Anna", 2: "Bob", 3: "Cleo", 4: "Dan", 5: "Eve", 6: "Finn", 7: "Gil", 8: "Hal"}


def game(round_=1, table=1, seats=((1, 10), (2, -4), (3, -6), (4, 0)), id_=1):
    return db.Game(id_, round_, table, tuple(seats))


# ------------------------------------------------------------------- card ----
def test_card_shows_heading_names_numbers_and_signed_points():
    out = html_views.card_html(game(2, 3), 5, 24, NAMES)
    assert "Round 2" in out and "Table 3" in out and "entry 5 of 24" in out
    for name in ("Anna", "Bob", "Cleo", "Dan"):
        assert name in out
    for number in ("#1", "#2", "#3", "#4"):
        assert number in out
    assert "+10" in out and "-4" in out and "-6" in out and "+0" in out


def test_card_keeps_seat_order():
    out = html_views.card_html(game(), 1, 1, NAMES)
    assert out.index("Anna") < out.index("Bob") < out.index("Cleo") < out.index("Dan")


def test_card_tints_every_top_scorer_and_only_them():
    single = html_views.card_html(game(seats=((1, 10), (2, -4), (3, -6), (4, 0))), 1, 1, NAMES)
    assert single.count(f'bgcolor="{html_views.WINNER_TINT}"') == 2        # name cell + points cell of one player
    tie = html_views.card_html(game(seats=((1, 5), (2, 5), (3, -5), (4, -5))), 1, 1, NAMES)
    assert tie.count(f'bgcolor="{html_views.WINNER_TINT}"') == 4           # two players share the top score


def test_card_marks_negative_points_red():
    out = html_views.card_html(game(seats=((1, 3), (2, -3), (3, 0), (4, 0))), 1, 1, NAMES)
    assert out.count(f"color:{html_views.NEGATIVE};") == 1


def test_card_escapes_html_in_names_and_falls_back_to_the_number():
    out = html_views.card_html(game(), 1, 1, {1: "<b>Evil</b> & Co", 2: "Bob", 3: "Cleo"})   # 4 has no name
    assert "<b>Evil</b>" not in out and "&lt;b&gt;Evil&lt;/b&gt; &amp; Co" in out
    assert "#4</span><br><b>4</b>" in out


# ---------------------------------------------------------------- ranking ----
def make_standings():
    games = [
        db.Game(1, 1, 1, ((1, 10), (2, -4), (3, -6), (4, 0))),
        db.Game(2, 1, 2, ((5, 7), (6, -7), (7, 0), (8, 0))),
        db.Game(3, 2, 1, ((1, -10), (5, 4), (3, 6), (6, 0))),        # players 2, 4, 7, 8 sit out round 2
    ]
    return ranking.compute(games, NAMES)


def test_ranking_has_one_column_per_round_plus_total():
    out = html_views.ranking_html(make_standings())
    assert ">R1<" in out and ">R2<" in out and ">R3<" not in out
    assert ">Total<" in out and "Ranking</h2>" in out


def test_ranking_rows_follow_the_standings_with_medals_for_the_top_three():
    st = make_standings()
    out = html_views.ranking_html(st)
    positions = [out.index(f"<b>{s.name}</b>") for s in st.rows]
    assert positions == sorted(positions)
    assert out.count("&#129351;") == 1 and out.count("&#129352;") >= 1


def test_ranking_round_cells_show_points_and_running_total_and_a_dash_for_sat_out_rounds():
    out = html_views.ranking_html(make_standings())
    assert "&ndash;" in out                                   # someone sat out round 2
    assert "+10" in out and "-10" in out


def test_ranking_marks_shared_ranks_only_when_there_are_ties():
    tied = ranking.compute([db.Game(1, 1, 1, ((1, 5), (2, 5), (3, -5), (4, -5)))], NAMES)
    assert "= marks a shared rank" in html_views.ranking_html(tied)
    distinct = ranking.compute([db.Game(1, 1, 1, ((1, 7), (2, 2), (3, -3), (4, -6)))], NAMES)
    assert not any(s.tied for s in distinct.rows)
    assert "= marks a shared rank" not in html_views.ranking_html(distinct)


def test_ranking_escapes_names():
    st = ranking.compute([db.Game(1, 1, 1, ((1, 1), (2, -1), (3, 0), (4, 0)))], {**NAMES, 1: "<i>x</i>"})
    out = html_views.ranking_html(st)
    assert "<i>x</i>" not in out and "&lt;i&gt;x&lt;/i&gt;" in out


def test_round_cell_formats():
    assert "&ndash;" in html_views.round_cell(7, None, "")
    assert "+3" in html_views.round_cell(7, 3, "") and "+7" in html_views.round_cell(7, 3, "")
    assert html_views.NEGATIVE in html_views.round_cell(-2, -2, "")


def test_card_puts_the_number_above_the_name_not_beside_it():
    out = html_views.card_html(game(), 1, 1, NAMES)
    for number, name in ((1, "Anna"), (2, "Bob"), (3, "Cleo"), (4, "Dan")):
        assert f"#{number}</span><br><b>{name}</b>" in out
        assert f"#{number}</span> <b>{name}</b>" not in out
