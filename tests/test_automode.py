import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tarock_presenter.automode import AutoMode, Cmd, Command, Stage  # noqa: E402

SHOW = lambda stage: Command(Cmd.SHOW_STAGE, stage)            # noqa: E731
STOP, CANCEL, RESUME = Command(Cmd.STOP_STAGE), Command(Cmd.CANCEL_RESUME_TIMER), Command(Cmd.START_RESUME_TIMER)


def test_starts_idle():
    auto = AutoMode()
    assert not auto.running and auto.stage is None and not auto.ever_started


def test_toggle_starts_at_first_stage_then_stops():
    auto = AutoMode()
    assert auto.toggle() == [CANCEL, SHOW(Stage.LOGO)]
    assert auto.running and auto.ever_started and auto.stage is Stage.LOGO
    assert auto.toggle() == [STOP, CANCEL]
    assert not auto.running and auto.ever_started          # "ever started" survives a stop


def test_default_cycle_alternates_logo_and_compare():
    auto = AutoMode()
    auto.toggle()
    shown = [auto.stage_finished()[0].stage for _ in range(5)]
    assert shown == [Stage.COMPARE, Stage.LOGO, Stage.COMPARE, Stage.LOGO, Stage.COMPARE]


def test_custom_cycle_with_walter():
    auto = AutoMode((Stage.LOGO, Stage.WALTER, Stage.COMPARE))
    auto.toggle()
    shown = [auto.stage_finished()[0].stage for _ in range(4)]
    assert shown == [Stage.WALTER, Stage.COMPARE, Stage.LOGO, Stage.WALTER]


def test_empty_cycle_rejected():
    with pytest.raises(ValueError):
        AutoMode(())


def test_stale_stage_finished_is_ignored_when_idle():
    auto = AutoMode()
    auto.toggle()
    auto.user_action()
    assert auto.stage_finished() == []                      # e.g. an animation signal that arrives late


def test_skip_from_logo_goes_to_compare_and_then_continues_normally():
    """Regression: the old code kept a magic state, so Compare was shown twice after a click."""
    auto = AutoMode()
    auto.toggle()                                           # LOGO
    assert auto.skip() == [SHOW(Stage.COMPARE)]
    assert auto.stage_finished() == [SHOW(Stage.LOGO)]      # not COMPARE again
    assert auto.stage_finished() == [SHOW(Stage.COMPARE)]


def test_skip_is_ignored_when_idle():
    assert AutoMode().skip() == []


def test_user_action_always_stops_and_cancels_resume():
    auto = AutoMode()
    assert auto.user_action() == [STOP, CANCEL]
    auto.toggle()
    assert auto.user_action() == [STOP, CANCEL] and not auto.running


def test_player_toggle_schedules_resume_only_after_auto_was_used():
    auto = AutoMode()
    assert auto.player_toggled() == [STOP, CANCEL]          # never started: nothing to resume
    auto.toggle()
    assert auto.player_toggled() == [STOP, CANCEL, RESUME]
    assert not auto.running


def test_compare_click_postpones_resume_only_while_idle_and_after_start():
    auto = AutoMode()
    assert auto.compare_clicked() == []                     # never started
    auto.toggle()
    assert auto.compare_clicked() == []                     # running: nothing pending
    auto.user_action()
    assert auto.compare_clicked() == [CANCEL, RESUME]


def test_resume_timeout_restarts_cycle():
    auto = AutoMode()
    auto.toggle()
    auto.player_toggled()
    assert auto.resume_timeout() == [CANCEL, SHOW(Stage.LOGO)]
    assert auto.running and auto.stage is Stage.LOGO


def test_resume_timeout_without_prior_start_does_nothing_but_cancel():
    auto = AutoMode()
    assert auto.resume_timeout() == [CANCEL] and not auto.running
