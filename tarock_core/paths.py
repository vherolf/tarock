"""Filesystem locations, independent of the current working directory.

From source, everything lives in the repository. In a PyInstaller build there are
two different places:
  * RESOURCE_ROOT - read-only files bundled into the executable (images/)
  * DATA_ROOT     - next to the executable: tournaments/, docs/ (user data, writable)
"""
from __future__ import annotations

import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)

REPO_ROOT = Path(__file__).resolve().parent.parent
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", REPO_ROOT)) if FROZEN else REPO_ROOT
DATA_ROOT = Path(sys.executable).resolve().parent if FROZEN else REPO_ROOT

TOURNAMENTS_DIR = DATA_ROOT / "tournaments"
DEFAULT_DB = TOURNAMENTS_DIR / "tournaments.db"


def sibling_program(name: str, script: str) -> list[str]:
    """Command line that starts another tool of this suite.

    From source: `python <script>`. Frozen: the executable `<name>` next to this one.
    """
    if FROZEN:
        exe = Path(sys.executable).resolve().parent / (name + (".exe" if sys.platform == "win32" else ""))
        return [str(exe)]
    return [sys.executable, str(REPO_ROOT / script)]


def ordinal(n: int) -> str:
    suffix = "th" if 11 <= (n % 100) <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"
