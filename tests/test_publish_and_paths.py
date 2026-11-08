import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tarock_core import consistency, csv_io, db, html_export  # noqa: E402


def make_tournament(base: Path, number: int = 1) -> Path:
    """Write a valid tournament folder via the real export code."""
    conn = db.open_rw(base / "t.db")
    db.set_players(conn, number, {i: f"P{i}" for i in range(1, 5)})
    db.save_game(conn, number, 1, 1, [(1, 10), (2, -5), (3, -5), (4, 0)])
    out = base / str(number)
    csv_io.export_tournament(conn, number, out)
    conn.close()
    return out


# ---------------------------------------------------------- published.txt ----
def test_published_requires_marker(tmp_path):
    make_tournament(tmp_path)
    with pytest.raises(SystemExit, match="not found"):
        html_export.published_tournament(tmp_path)


def test_published_uses_named_tournament_not_latest(tmp_path):
    make_tournament(tmp_path, 1)
    make_tournament(tmp_path, 2)          # newer, but not published
    (tmp_path / "published.txt").write_text("1\n")
    assert html_export.published_tournament(tmp_path).name == "1"


@pytest.mark.parametrize("content,msg", [("abc", "must contain"), ("9", "does not exist")])
def test_published_rejects_bad_marker(tmp_path, content, msg):
    make_tournament(tmp_path)
    (tmp_path / "published.txt").write_text(content)
    with pytest.raises(SystemExit, match=msg):
        html_export.published_tournament(tmp_path)


# ------------------------------------------------------------ consistency ----
def test_consistent_data_passes(tmp_path):
    d = make_tournament(tmp_path)
    assert consistency.check_tournament_dir(d) == []


def test_stale_ranking_is_detected(tmp_path):
    d = make_tournament(tmp_path)
    text = (d / "ranking.csv").read_text().replace(",10", ",11")   # hand-edited total
    (d / "ranking.csv").write_text(text)
    problems = consistency.check_tournament_dir(d)
    assert any("does not match result.csv" in p for p in problems)


def test_result_change_without_ranking_update_is_detected(tmp_path):
    d = make_tournament(tmp_path)
    lines = (d / "result.csv").read_text().splitlines()
    lines[1] = "1,1,1,7,2,-2,3,-5,4,0"                                 # still sums to 0, totals differ
    (d / "result.csv").write_text("\n".join(lines) + "\n")
    assert any("does not match" in p for p in consistency.check_tournament_dir(d))


def test_invalid_result_is_detected(tmp_path):
    d = make_tournament(tmp_path)
    lines = (d / "result.csv").read_text().splitlines()
    lines[1] = "1,1,1,10,2,-5,3,-5,4,5"                                 # does not sum to 0
    (d / "result.csv").write_text("\n".join(lines) + "\n")
    assert any("sum to 0" in p for p in consistency.check_tournament_dir(d))


def test_check_all_reports_marker(tmp_path):
    make_tournament(tmp_path)
    assert consistency.check_all(tmp_path)["published.txt"]            # missing
    (tmp_path / "published.txt").write_text("1")
    assert all(not p for p in consistency.check_all(tmp_path).values())


# ------------------------------------------------------------------ paths ----
def reload_paths(monkeypatch, frozen: bool, meipass=None, executable=None):
    from tarock_core import paths
    if frozen:
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
        monkeypatch.setattr(sys, "executable", str(executable))
    else:
        monkeypatch.delattr(sys, "frozen", raising=False)
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    return importlib.reload(paths)


def test_paths_from_source_use_repo(monkeypatch):
    p = reload_paths(monkeypatch, frozen=False)
    assert p.DATA_ROOT == p.RESOURCE_ROOT == p.REPO_ROOT
    assert p.TOURNAMENTS_DIR == p.REPO_ROOT / "tournaments"
    assert p.sibling_program("presenter", "presenter.py")[-1].endswith("presenter.py")


def test_paths_frozen_separate_resources_and_data(monkeypatch, tmp_path):
    exe_dir, bundle = tmp_path / "app", tmp_path / "_MEI123"
    exe_dir.mkdir(); bundle.mkdir()
    p = reload_paths(monkeypatch, frozen=True, meipass=bundle, executable=exe_dir / "tarockmanager")
    assert p.RESOURCE_ROOT == bundle                       # bundled images
    assert p.DATA_ROOT == exe_dir.resolve()                # writable data next to the exe
    assert p.DEFAULT_DB == exe_dir.resolve() / "tournaments" / "tournaments.db"
    assert p.sibling_program("presenter", "presenter.py") == [str(exe_dir.resolve() / "presenter")]
    reload_paths(monkeypatch, frozen=False)                # restore module state for other tests


# ------------------------------------------------------------------- imports ----
def test_data_check_needs_no_image_library():
    """The consistency check runs in CI before anything else; it must not need qrcode (used only for the page)."""
    import subprocess
    code = ("import sys; sys.modules['qrcode'] = None; "
            "import tarock_core.consistency, tarock_core.csv_io, tarock_core.ranking; print('ok')")
    result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parent.parent,
                            capture_output=True, text=True)
    assert result.stdout.strip() == "ok", result.stderr
