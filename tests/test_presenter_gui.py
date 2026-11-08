"""Headless GUI tests for the presentation window (Qt 'offscreen' platform)."""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pytest.importorskip("PyQt6")
pytest.importorskip("matplotlib")

from PyQt6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QPushButton, QStackedWidget  # noqa: E402

from tarock_core import db, ranking  # noqa: E402
from tarock_presenter.automode import Stage  # noqa: E402
from tarock_presenter.window import COMPARE, RANKING, SPLASH, WALTER, GraphWindow  # noqa: E402

NAMES = {i: f"Player{i}" for i in range(1, 9)}


def make_standings(n_games: int = 4):
    games = [
        db.Game(1, 1, 1, ((1, 10), (2, -5), (3, -5), (4, 0))),
        db.Game(2, 1, 2, ((5, 7), (6, -7), (7, 0), (8, 0))),
        db.Game(3, 2, 1, ((1, -2), (5, 4), (3, -2), (6, 0))),
        db.Game(4, 2, 2, ((2, 6), (4, -3), (7, -3), (8, 0))),
    ]
    return ranking.compute(games[:n_games], NAMES)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def make_window(app):
    windows = []

    def factory(**kwargs):
        win = GraphWindow(kwargs.pop("standings", make_standings()), title="Test", **kwargs)
        win.resize(1280, 800)
        win.show()
        spin(50)
        windows.append(win)
        return win

    yield factory
    for win in windows:
        win.close()


def spin(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def key(win, k) -> None:
    QTest.keyClick(win, k)


def button(win, text: str) -> QPushButton:
    return next(b for b in win.findChildren(QPushButton) if b.text() == text and b.isVisible())


def page_changes(win, ms: int) -> list[int]:
    seq: list[int] = []
    win.findChild(QStackedWidget).currentChanged.connect(seq.append)
    spin(ms)
    return seq


# ------------------------------------------------------------------ navigation
def test_starts_on_splash_and_arrows_walk_through_pages(make_window):
    win = make_window()
    stack = win.findChild(QStackedWidget)
    assert stack.currentIndex() == SPLASH
    key(win, Qt.Key.Key_Right)
    assert stack.currentIndex() == RANKING
    key(win, Qt.Key.Key_Right)
    assert stack.currentIndex() == COMPARE
    key(win, Qt.Key.Key_Right)
    assert stack.currentIndex() == SPLASH          # wraps back to the logo
    key(win, Qt.Key.Key_W)
    assert stack.currentIndex() == WALTER
    key(win, Qt.Key.Key_W)
    assert stack.currentIndex() == SPLASH


def test_space_reveals_ranking_rows_from_last_place_up(make_window):
    win = make_window()
    key(win, Qt.Key.Key_Right)
    assert win._ranking.revealed == 0
    key(win, Qt.Key.Key_Space)
    assert win._ranking.revealed == 1
    for _ in range(20):
        key(win, Qt.Key.Key_Space)
    assert win._ranking.all_revealed and win._ranking.revealed == win._ranking.count == len(NAMES)


def test_space_does_nothing_outside_the_ranking(make_window):
    win = make_window()
    key(win, Qt.Key.Key_Space)
    assert win._ranking.revealed == 0


def test_ranking_button_on_ranking_reveals_next_row(make_window):
    win = make_window()
    QTest.mouseClick(button(win, "Ranking"), Qt.MouseButton.LeftButton)     # from splash: go to ranking
    assert win._ranking.revealed == 0
    QTest.mouseClick(button(win, "Ranking"), Qt.MouseButton.LeftButton)     # on ranking: reveal next
    assert win._ranking.revealed == 1


def test_compare_selection_toggles(make_window):
    win = make_window()
    key(win, Qt.Key.Key_Right)
    key(win, Qt.Key.Key_Right)
    first = win._view.players[0]
    QTest.mouseClick(button(win, f"{first.rank}. {first.name}"), Qt.MouseButton.LeftButton)
    assert win._compare.selected == {first.pnum}
    QTest.mouseClick(button(win, f"{first.rank}. {first.name}"), Qt.MouseButton.LeftButton)
    assert win._compare.selected == set()


# ------------------------------------------------------------------- auto mode
def test_auto_mode_alternates_logo_and_compare_and_stops(make_window):
    win = make_window(auto_speed=0.05)
    key(win, Qt.Key.Key_A)
    seq = page_changes(win, 1800)
    assert seq[:4] == [COMPARE, SPLASH, COMPARE, SPLASH]
    assert any(b.text() == "Pause" for b in win.findChildren(QPushButton))
    key(win, Qt.Key.Key_A)
    assert page_changes(win, 700) == []
    assert all(b.text() == "Auto" for b in win.findChildren(QPushButton) if b.text() in ("Auto", "Pause"))


def test_auto_mode_with_walter_stage(make_window):
    win = make_window(auto_speed=0.05, auto_cycle=(Stage.LOGO, Stage.WALTER, Stage.COMPARE))
    key(win, Qt.Key.Key_A)
    seq = page_changes(win, 3500)
    assert seq[:3] == [WALTER, COMPARE, SPLASH]


def test_user_navigation_stops_auto_mode(make_window):
    win = make_window(auto_speed=0.05)
    key(win, Qt.Key.Key_A)
    spin(200)
    QTest.mouseClick(button(win, "Compare"), Qt.MouseButton.LeftButton)
    index = win.findChild(QStackedWidget).currentIndex()
    assert index == COMPARE
    assert page_changes(win, 900) == []             # stays put; no auto-resume after a plain navigation


def test_compare_interaction_resumes_auto_mode_later(make_window):
    win = make_window(auto_speed=0.05, auto_resume_s=1)
    key(win, Qt.Key.Key_A)
    spin(100)
    QTest.mouseClick(button(win, "Compare"), Qt.MouseButton.LeftButton)
    spin(50)
    first = win._view.players[0]
    QTest.mouseClick(button(win, f"{first.rank}. {first.name}"), Qt.MouseButton.LeftButton)
    spin(100)
    seq = page_changes(win, 2000)
    assert seq and seq[0] == SPLASH                  # resumed by itself with the logo


def test_walter_key_stops_auto_mode(make_window):
    win = make_window(auto_speed=0.05)
    key(win, Qt.Key.Key_A)
    spin(150)
    key(win, Qt.Key.Key_W)
    assert win.findChild(QStackedWidget).currentIndex() == WALTER
    assert page_changes(win, 900) == []


def test_clicking_the_logo_during_auto_skips_to_compare_and_then_back(make_window):
    win = make_window(auto_speed=0.2)
    key(win, Qt.Key.Key_A)
    spin(80)
    assert win.findChild(QStackedWidget).currentIndex() == SPLASH
    QTest.mouseClick(win._splash._content, Qt.MouseButton.LeftButton)
    assert win.findChild(QStackedWidget).currentIndex() == COMPARE
    assert win._auto.stage is Stage.COMPARE
    win._on_stage_finished()
    assert win._auto.stage is Stage.LOGO              # regression: used to show Compare a second time


# ----------------------------------------------------------------- live update
def test_live_update_keeps_view_state(make_window):
    win = make_window()
    key(win, Qt.Key.Key_Right)
    for _ in range(3):
        key(win, Qt.Key.Key_Space)
    key(win, Qt.Key.Key_Right)
    first = win._view.players[0]
    QTest.mouseClick(button(win, f"{first.rank}. {first.name}"), Qt.MouseButton.LeftButton)
    key(win, Qt.Key.Key_Left)                         # back to the ranking, 3 rows revealed
    selected_before = win._compare.selected

    win.update_standings(make_standings(n_games=3))
    stack = win.findChild(QStackedWidget)
    assert stack.currentIndex() == RANKING
    assert win._ranking.revealed == 3
    assert win._compare.selected == selected_before


def test_live_update_with_everything_revealed_reveals_new_rows_too(make_window):
    win = make_window(standings=make_standings(n_games=3))
    key(win, Qt.Key.Key_Right)
    for _ in range(20):
        key(win, Qt.Key.Key_Space)
    assert win._ranking.all_revealed
    win.update_standings(make_standings(n_games=4))
    assert win._ranking.all_revealed and win._ranking.count == len(NAMES)


def test_identical_standings_do_not_rebuild_pages(make_window):
    win = make_window()
    ranking_page, compare_page = win._ranking, win._compare
    win.update_standings(make_standings())
    assert win._ranking is ranking_page and win._compare is compare_page


def test_live_update_keeps_auto_button_state(make_window):
    win = make_window(auto_speed=0.05)
    key(win, Qt.Key.Key_A)
    win.update_standings(make_standings(n_games=3))
    assert any(b.text() == "Pause" for b in win._ranking.findChildren(QPushButton))
    assert any(b.text() == "Pause" for b in win._compare.findChildren(QPushButton))


def test_empty_tournament_is_shown_without_errors(make_window):
    win = make_window(standings=ranking.compute([], NAMES))
    for k in (Qt.Key.Key_Right, Qt.Key.Key_Space, Qt.Key.Key_Right, Qt.Key.Key_A, Qt.Key.Key_A):
        key(win, k)
    win.update_standings(make_standings())
    assert win._ranking.count == len(NAMES)
