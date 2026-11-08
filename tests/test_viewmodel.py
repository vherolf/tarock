import math
import random
import sys
from pathlib import Path

import matplotlib.colors as mcolors

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tarock_core import db, ranking  # noqa: E402
from tarock_presenter import viewmodel  # noqa: E402

NAMES = {i: f"P{i}" for i in range(1, 9)}


def standings(*games):
    return ranking.compute([db.Game(i + 1, r, i + 1, tuple(s)) for i, (r, s) in enumerate(games)], NAMES)


def test_view_follows_ranking_and_carries_cumulative_totals():
    st = standings((1, [(1, 10), (2, -5), (3, -5), (4, 0)]), (2, [(1, -3), (2, 8), (5, -5), (6, 0)]))
    view = viewmodel.build_view(st)
    assert view.rounds == (1, 2)
    assert [p.pnum for p in view.players] == [str(s.player) for s in st.rows]
    by = {p.pnum: p for p in view.players}
    assert by["1"].cumulative == (10, 7) and by["1"].total == 7
    assert by["2"].cumulative == (-5, 3)
    assert by["5"].cumulative == (0, -5)        # sat out round 1: total carries over


def test_colors_are_unique_up_to_palette_size_and_stable_across_updates():
    first = viewmodel.assign_colors([str(i) for i in range(1, 9)])
    assert len(set(first.values())) == 8
    # a new player appears, the order changes: existing players keep their colour
    second = viewmodel.assign_colors(["9", "3", "1", "2"] + [str(i) for i in range(4, 9)], first)
    assert all(second[p] == first[p] for p in first)
    assert second["9"] not in first.values()


def test_colors_repeat_only_when_palette_is_exhausted():
    n = len(viewmodel.PLAYER_COLORS) + 2
    colors = viewmodel.assign_colors([str(i) for i in range(n)])
    assert len(colors) == n
    assert len(set(colors.values())) == len(viewmodel.PLAYER_COLORS)


def test_players_that_left_release_their_colors():
    first = viewmodel.assign_colors(["1", "2"])
    again = viewmodel.assign_colors(["2", "3"], first)
    assert again["2"] == first["2"] and "1" not in again


# ----------------------------------------------------------------- palette ----
def _lab(color: str) -> tuple[float, float, float]:
    """CIE Lab of a colour (D65), to judge distinctness the way the eye does."""
    r, g, b = [(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4) for v in mcolors.to_rgb(color)]
    x, y, z = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047, 0.2126 * r + 0.7152 * g + 0.0722 * b, \
              (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883
    f = lambda t: t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116   # noqa: E731
    return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))


def test_palette_has_room_for_the_mapping_panel_and_is_unique():
    assert len(viewmodel.PLAYER_COLORS) >= 20          # the mapping panel has 20 rows
    resolved = [mcolors.to_hex(c).lower() for c in viewmodel.PLAYER_COLORS]
    assert len(set(resolved)) == len(resolved)


def test_original_colors_are_kept_for_the_first_players():
    assert viewmodel.PLAYER_COLORS[:3] == ("gold", "silver", "#CD7F32")
    assert len(viewmodel.PLAYER_COLORS) > 14


def test_palette_colors_are_distinguishable_and_readable_on_the_dark_background():
    colors = viewmodel.PLAYER_COLORS
    for color in colors:
        assert _lab(color)[0] >= 50, f"{color} is too dark for the dark background"   # darkest original: steelblue (52)
    closest = min(
        math.dist(_lab(a), _lab(b)) for i, a in enumerate(colors) for b in colors[i + 1:]
    )
    assert closest >= 20, f"two palette colours are nearly identical (distance {closest:.1f})"


def test_sixteen_and_twenty_players_all_get_different_colors():
    for n in (16, 20, 24):
        colors = viewmodel.assign_colors([str(i) for i in range(1, n + 1)])
        assert len(set(colors.values())) == n


# ------------------------------------------------------- auto-mode comparison ----
PLAYERS = [str(i) for i in range(1, 17)]            # ranking order: "1" is the winner, "16" the last


def test_compare_picks_three_distinct_players():
    for seed in range(50):
        picked = viewmodel.pick_compare_players(PLAYERS, random.Random(seed))
        assert len(picked) == viewmodel.COMPARE_SIZE == 3 and len(set(picked)) == 3


def test_the_anchor_is_always_one_of_the_top_three_never_a_last_place():
    anchors = {viewmodel.pick_compare_players(PLAYERS, random.Random(seed))[0] for seed in range(300)}
    assert anchors == {"1", "2", "3"}                 # all three winners get their turn, nobody else is ever the anchor


def test_the_two_random_players_can_be_anyone_but_the_anchor_and_never_repeat():
    rng = random.Random(1)
    others = set()
    for _ in range(600):
        anchor, a, b = viewmodel.pick_compare_players(PLAYERS, rng)
        assert anchor not in (a, b) and a != b
        others |= {a, b}
    assert others == set(PLAYERS)


def test_small_tournaments_show_everyone():
    assert viewmodel.pick_compare_players(["1", "2", "3"]) == ["1", "2", "3"]
    assert viewmodel.pick_compare_players(["1"]) == ["1"]
    assert viewmodel.pick_compare_players([]) == []
    four = viewmodel.pick_compare_players(["1", "2", "3", "4"], random.Random(0))
    assert len(four) == 3 and four[0] in ("1", "2", "3")
