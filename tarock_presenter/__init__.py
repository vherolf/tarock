"""Presentation window (read-only). See presenter.py for the entry point.

automode.py   pure auto-mode state machine (no Qt, unit-tested)
viewmodel.py  pure display data derived from the standings (no Qt, unit-tested)
widgets.py    low-level Qt painting helpers
pages.py      one class per page (splash, ranking, compare, Walter) + shared header bar
window.py     GraphWindow: wires pages, navigation, timers and the state machine together
"""
