"""GraphWindow: the presentation window.

Wires the pages together and owns navigation, timers and the auto-mode state machine.
Rules live elsewhere: what auto mode does is decided by `automode.AutoMode` (pure),
what is drawn by the page classes, what numbers are shown by `viewmodel` / `tarock_core`.
"""
from __future__ import annotations


from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from tarock_core import ranking

from .automode import AutoMode, Cmd, Command, DEFAULT_CYCLE, Stage
from .pages import ComparePage, NavBar, RankingPage, SplashPage, WalterPage
from .viewmodel import View, build_view, pick_compare_players

# how long auto mode shows the comparison (before the speed factor); override with --compare-seconds
AUTO_COMPARE_SECONDS = 20.0

# stack indices
SPLASH, RANKING, COMPARE, WALTER = 0, 1, 2, 3
# the two "frames" the arrow keys step through after the splash
FRAME_RANKING, FRAME_COMPARE = 0, 1


class GraphWindow(QWidget):
    AUTO_COMPARE_MS = int(AUTO_COMPARE_SECONDS * 1_000)   # default length of the compare stage

    def __init__(
        self,
        standings: ranking.Standings,
        title: str = "Pony Tarock Championship",
        auto_speed: float = 1.0,
        auto_resume_s: int = 180,
        auto_cycle: tuple[Stage, ...] = DEFAULT_CYCLE,
        compare_seconds: float = AUTO_COMPARE_SECONDS,
    ) -> None:
        super().__init__()
        self._title = title
        self.setWindowTitle(title)
        self.resize(960, 700)

        # Scale all auto-mode durations by auto_speed (2.0 = twice as slow)
        def ms(base: int) -> int:
            return max(100, int(base * auto_speed))

        self._logo_fade_in_ms = ms(2_000)
        self._logo_hold_ms = ms(2_000)
        self._logo_fade_out_ms = ms(1_000)
        self._compare_ms = ms(int(compare_seconds * 1_000))
        self._walter_hold_ms = ms(3_000)

        self._standings = standings
        self._view: View = build_view(standings)
        self._frame = FRAME_RANKING
        self._advert_prev_index = SPLASH

        # ---- auto mode: pure state machine + the timers that execute its commands ----
        self._auto = AutoMode(auto_cycle)
        self._stage_timer = QTimer(self)          # ends the compare stage / the post-wipe pause
        self._stage_timer.setSingleShot(True)
        self._stage_timer.timeout.connect(self._on_stage_finished)
        self._walter_hold_timer = QTimer(self)    # how long the advert stays before it wipes away
        self._walter_hold_timer.setSingleShot(True)
        self._walter_hold_timer.timeout.connect(self._start_walter_wipe)
        self._resume_timer = QTimer(self)         # inactivity before auto mode resumes by itself
        self._resume_timer.setSingleShot(True)
        self._resume_timer.setInterval(auto_resume_s * 1_000)
        self._resume_timer.timeout.connect(lambda: self._run(self._auto.resume_timeout()))

        # ---- pages ----
        self._stack = QStackedWidget()
        self._splash = SplashPage(title)
        self._walter = WalterPage(title)
        self._ranking, self._compare = self._make_data_pages()
        for page in (self._splash, self._ranking, self._compare, self._walter):   # = stack indices
            self._stack.addWidget(page)
        self._wire_static_pages()
        self._wire_data_pages()
        self._stack.setCurrentIndex(SPLASH)

        layout = QVBoxLayout(self)
        layout.addWidget(self._stack)

        for key, handler in (
            (Qt.Key.Key_Left, self._user_back),
            (Qt.Key.Key_Right, self._user_forward),
            (Qt.Key.Key_F11, self._toggle_fullscreen),
            (Qt.Key.Key_F, self._toggle_fullscreen),
            (Qt.Key.Key_Escape, self._exit_fullscreen),
            (Qt.Key.Key_Space, self._reveal_next),
            (Qt.Key.Key_A, self._toggle_auto),
            (Qt.Key.Key_W, self._toggle_walter_advert),
        ):
            QShortcut(QKeySequence(key), self).activated.connect(handler)

    # ------------------------------------------------------------------ pages
    def _make_data_pages(self) -> tuple[RankingPage, ComparePage]:
        return RankingPage(self._title, self._view), ComparePage(self._title, self._view)

    def _nav_bars(self) -> list[NavBar]:
        return [page.nav for page in (self._splash, self._ranking, self._compare, self._walter)]

    def _wire_nav(self, nav: NavBar) -> None:
        nav.logo.connect(self._jump_to_logo)
        nav.ranking.connect(self._jump_to_ranking)
        nav.compare.connect(self._jump_to_compare)
        nav.auto.connect(self._toggle_auto)

    def _wire_static_pages(self) -> None:
        """Pages that never change with the data (splash, advert)."""
        self._wire_nav(self._splash.nav)
        self._wire_nav(self._walter.nav)
        self._splash.pressed.connect(lambda: self._run(self._auto.skip()))
        self._walter.pressed.connect(lambda: self._run(self._auto.skip()))

    def _wire_data_pages(self) -> None:
        """Pages rebuilt when the data changes (ranking, compare)."""
        self._wire_nav(self._ranking.nav)
        self._wire_nav(self._compare.nav)
        self._compare.playerToggled.connect(lambda _p: self._run(self._auto.player_toggled()))
        self._compare.chartPressed.connect(lambda: self._run(self._auto.compare_clicked()))

    def update_standings(self, standings: ranking.Standings) -> None:
        """Live refresh: rebuild the data-dependent pages, keeping the view state."""
        if standings == self._standings:
            return
        was_all_revealed = self._ranking.all_revealed
        revealed = self._ranking.revealed
        selected = self._compare.selected
        current = self._stack.currentIndex()

        self._standings = standings
        self._view = build_view(standings, {p.pnum: p.color for p in self._view.players})
        old_ranking, old_compare = self._ranking, self._compare
        self._ranking, self._compare = self._make_data_pages()
        for index, old, new in ((RANKING, old_ranking, self._ranking), (COMPARE, old_compare, self._compare)):
            self._stack.removeWidget(old)
            old.deleteLater()
            self._stack.insertWidget(index, new)
        self._wire_data_pages()
        self._stack.setCurrentIndex(current)

        self._ranking.set_revealed(self._ranking.count if was_all_revealed else revealed)
        self._compare.set_selected(selected)
        self._sync_auto_ui()
        self._ranking.update_font_size()
        self._compare.redraw()

    # ------------------------------------------------------------- auto mode
    def _run(self, commands: list[Command]) -> None:
        """Execute what the state machine asked for, then refresh the Auto/Pause buttons."""
        for command in commands:
            if command.kind is Cmd.SHOW_STAGE:
                self._show_stage(command.stage)
            elif command.kind is Cmd.STOP_STAGE:
                self._halt_stage()
            elif command.kind is Cmd.START_RESUME_TIMER:
                self._resume_timer.start()
            elif command.kind is Cmd.CANCEL_RESUME_TIMER:
                self._resume_timer.stop()
        self._sync_auto_ui()

    def _sync_auto_ui(self) -> None:
        text = "Pause" if self._auto.running else "Auto"
        pending = self._resume_timer.isActive()
        for nav in self._nav_bars():
            nav.set_auto_text(text)
            nav.set_resume_visible(pending)

    def _halt_stage(self) -> None:
        self._stage_timer.stop()
        self._walter_hold_timer.stop()
        self._splash.stop_fade()
        self._walter.stop_pixelout()

    def _show_stage(self, stage: Stage) -> None:
        self._halt_stage()
        if stage is Stage.LOGO:
            self._stack.setCurrentIndex(SPLASH)
            self._splash.play_fade(
                self._logo_fade_in_ms, self._logo_hold_ms, self._logo_fade_out_ms, self._on_stage_finished
            )
        elif stage is Stage.COMPARE:
            ranked = [p.pnum for p in self._view.players]
            self._compare.set_selected(set(pick_compare_players(ranked)))
            self._frame = FRAME_COMPARE
            self._show_frame()
            self._stage_timer.start(self._compare_ms)
        elif stage is Stage.WALTER:
            self._stack.setCurrentIndex(WALTER)
            self._walter_hold_timer.start(self._walter_hold_ms)

    def _on_stage_finished(self) -> None:
        self._run(self._auto.stage_finished())

    def _start_walter_wipe(self) -> None:
        self._walter.start_pixelout(lambda: self._stage_timer.start(1000))

    def _toggle_auto(self) -> None:
        self._run(self._auto.toggle())

    def _user_action(self) -> None:
        """Manual navigation: auto mode stops."""
        self._run(self._auto.user_action())

    # ------------------------------------------------------------ navigation
    def _show_frame(self) -> None:
        if self._frame == FRAME_RANKING:
            self._stack.setCurrentIndex(RANKING)
            self._ranking.update_font_size()
        else:
            self._stack.setCurrentIndex(COMPARE)
            self._compare.redraw()

    def _reveal_next(self) -> None:
        """Manually reveal the next hidden ranking row (Space key)."""
        if self._stack.currentIndex() == RANKING:
            self._ranking.reveal_next()

    def _toggle_walter_advert(self) -> None:
        if self._stack.currentIndex() == WALTER:
            self._stack.setCurrentIndex(self._advert_prev_index)
        else:
            self._advert_prev_index = self._stack.currentIndex()
            self._user_action()
            self._stack.setCurrentIndex(WALTER)

    def _user_forward(self) -> None:
        self._user_action()
        if self._leave_splash():
            return
        if self._frame == FRAME_RANKING:
            self._frame = FRAME_COMPARE
            self._show_frame()
        else:                                   # after the compare page: back to the logo
            self._frame = FRAME_RANKING
            self._stack.setCurrentIndex(SPLASH)

    def _user_back(self) -> None:
        self._user_action()
        if self._leave_splash():
            return
        self._frame = FRAME_COMPARE if self._frame == FRAME_RANKING else FRAME_RANKING
        self._show_frame()

    def _leave_splash(self) -> bool:
        """From the splash, any arrow key goes to the ranking."""
        if self._stack.currentIndex() != SPLASH:
            return False
        self._stack.setCurrentIndex(RANKING)
        return True

    def _jump_to_logo(self) -> None:
        self._user_action()
        self._stack.setCurrentIndex(SPLASH)

    def _jump_to_ranking(self) -> None:
        self._user_action()
        if self._stack.currentIndex() == RANKING:
            self._ranking.reveal_next()          # pressing "Ranking" on the ranking reveals the next row
        else:
            self._frame = FRAME_RANKING
            self._ranking.hide_all()
            self._stack.setCurrentIndex(RANKING)

    def _jump_to_compare(self) -> None:
        self._user_action()
        self._frame = FRAME_COMPARE
        self._show_frame()

    # ---------------------------------------------------------------- window
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._ranking.update_font_size()

    def _exit_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def closeEvent(self, event) -> None:
        self._halt_stage()
        self._resume_timer.stop()
        super().closeEvent(event)
