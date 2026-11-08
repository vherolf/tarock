"""Filesystem locations, independent of the current working directory."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOURNAMENTS_DIR = REPO_ROOT / "tournaments"
DEFAULT_DB = TOURNAMENTS_DIR / "tournaments.db"


def ordinal(n: int) -> str:
    suffix = "th" if 11 <= (n % 100) <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"
