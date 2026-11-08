"""Auto-mode state machine - pure logic, no Qt.

The window owns the timers and animations; this class only decides *what should happen*
when something happens, and answers with commands. That keeps the rules in one place and
lets them be unit-tested without a display.

Auto mode cycles through stages (default: logo -> compare -> logo ...). It can be:
  * running  - a stage is active (shown, with its timer/animation)
  * idle     - stopped by the user
  * idle with a pending "resume" timer - after the user interacted with the compare page
"""
from __future__ import annotations

from enum import Enum
from typing import NamedTuple


class Stage(Enum):
    LOGO = "logo"
    WALTER = "walter"
    COMPARE = "compare"


class Cmd(Enum):
    SHOW_STAGE = "show_stage"                  # stage: the stage to show
    STOP_STAGE = "stop_stage"                  # halt running timers/animations of the current stage
    START_RESUME_TIMER = "start_resume_timer"  # (re)start the inactivity timer, show the hint
    CANCEL_RESUME_TIMER = "cancel_resume_timer"


class Command(NamedTuple):
    kind: Cmd
    stage: Stage | None = None


DEFAULT_CYCLE = (Stage.LOGO, Stage.COMPARE)


class AutoMode:
    def __init__(self, cycle: tuple[Stage, ...] = DEFAULT_CYCLE) -> None:
        if not cycle:
            raise ValueError("the auto-mode cycle needs at least one stage")
        self._cycle = tuple(cycle)
        self._pos: int | None = None   # index into the cycle; None = not running
        self.ever_started = False      # auto mode was started at least once (enables auto-resume)

    # ---- state -------------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._pos is not None

    @property
    def stage(self) -> Stage | None:
        return None if self._pos is None else self._cycle[self._pos]

    # ---- events (each returns the commands the window must execute, in order) ----
    def toggle(self) -> list[Command]:
        """The Auto/Pause button or the A key."""
        if self.running:
            self._pos = None
            return [Command(Cmd.STOP_STAGE), Command(Cmd.CANCEL_RESUME_TIMER)]
        self.ever_started = True
        return [Command(Cmd.CANCEL_RESUME_TIMER), self._enter(0)]

    def user_action(self) -> list[Command]:
        """Any manual navigation (buttons, arrow keys, the Walter key): auto mode stops."""
        self._pos = None
        return [Command(Cmd.STOP_STAGE), Command(Cmd.CANCEL_RESUME_TIMER)]

    def player_toggled(self) -> list[Command]:
        """A player was (de)selected on the compare page: stop, and auto-resume later if auto was used."""
        commands = self.user_action()
        if self.ever_started:
            commands.append(Command(Cmd.START_RESUME_TIMER))
        return commands

    def compare_clicked(self) -> list[Command]:
        """The compare chart was clicked: postpone a pending auto-resume (only while auto is idle)."""
        if self.ever_started and not self.running:
            return [Command(Cmd.CANCEL_RESUME_TIMER), Command(Cmd.START_RESUME_TIMER)]
        return []

    def stage_finished(self) -> list[Command]:
        """The current stage ran its course (timer or animation ended): go to the next one."""
        if not self.running:
            return []  # a stale event from a stage the user already stopped
        return [self._enter((self._pos + 1) % len(self._cycle))]

    def skip(self) -> list[Command]:
        """The user clicked the logo/advert while auto mode runs: jump to the next stage."""
        return self.stage_finished()

    def resume_timeout(self) -> list[Command]:
        """The inactivity timer fired: start the cycle again."""
        if not self.ever_started:
            return [Command(Cmd.CANCEL_RESUME_TIMER)]
        return [Command(Cmd.CANCEL_RESUME_TIMER), self._enter(0)]

    # ---- internals -----------------------------------------------------------
    def _enter(self, pos: int) -> Command:
        self._pos = pos
        return Command(Cmd.SHOW_STAGE, self._cycle[pos])
