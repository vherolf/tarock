# Tarock Tournament Manager

Two PyQt6 desktop tools for 4-player Tarock tournaments: one for recording results, one for an animated results presentation with comparison graphs, sharing a SQLite database.

---

## Requirements

- Python 3.10+
- pip

---

## Installation

```bash
# Clone or download the repository, then enter the project folder
cd tarock

# (Recommended) Create a virtual environment
python -m venv venv
source venv/bin/activate        # Linux / macOS
venv\Scripts\activate           # Windows

# Install dependencies
pip install -r requirements.txt
```

---

## Architecture

Two separate programs share one SQLite database (`tournaments/tournaments.db`):

| Program | Role | Database access |
|---|---|---|
| `tarockmanager.py` | Data entry: players, table results, ranking view | read / write |
| `presenter.py` | Animated results presentation | **read-only** (SQLite rejects any write) |
| `tarock_core/` | Shared, Qt-free code: schema + validation (`db.py`), ranking rules (`ranking.py`), CSV import/export (`csv_io.py`) | - |

The database is the single source of truth. It is local and gitignored. After every change the entry tool also writes
`result.csv`, `player_numbers.csv` and `ranking.csv` to `tournaments/<N>/` (derived copies, committed for the GitHub Pages site).
`ranking.csv` is regenerated on every save, so it cannot be stale.

### Data integrity
- Only registered players can score, a player sits at one table per round, a table is used once per round, every game has exactly 4 players and its points sum to 0. These are checked in the app *and* enforced by the schema (foreign keys, UNIQUE, CHECK).
- Every write is one transaction: a rejected change leaves the old data untouched.
- Both tools audit the data on start-up and warn about inconsistencies.

### Ranking rules (`tarock_core/ranking.py`)
1. Total points. 2. Most table wins (highest score at a table in a round; shared top score = a win each). 3. Best single-round score.
Players still equal share a rank (1, 2, 2, 4) and are listed by name. Ranking is computed in this one place only.

---

## Running

```bash
python tarockmanager.py        # data entry
python presenter.py      # presentation (separate program, read-only)
```

Both accept `--db PATH` (default `tournaments/tournaments.db`, independent of the working directory) and
`-t N` / `--tournament N` (latest if omitted; the entry tool creates a new tournament if `N` does not exist).
The presentation also accepts:

| Argument | Short | Default | Description |
|---|---|---|---|
| `--speed-auto-mode X` | `-s` | `1.0` | Auto-mode speed multiplier. `0.5` is twice as fast, `2.0` twice as slow. |
| `--auto-resume SEC` | `-r` | `180` | Seconds of inactivity on the compare page before auto mode resumes. |

The presentation updates live: it polls the database (about once a second) and rebuilds the ranking and compare pages when the entry tool saves, keeping the current page, the revealed rows and the selected players. It never writes to the database.

### Importing legacy CSV data

```bash
python scripts/import_csv.py [N ...] [--compare]
```
Validates every row and imports each tournament all-or-nothing. Invalid rows are listed, never skipped silently.

### Tests

```bash
python -m pytest tests
```

---

## Usage (data entry)

### Player mapping (left panel)
Fill in numbers and names, then **Save Mapping**. Names must be unique; a player who already has results cannot be removed.

### Recording results (right panel)
1. Set **Round** and **Table Number**, then the 4 player numbers (must be in the mapping) and points (must sum to 0).
2. **Submit** (`Ctrl+S`) stores the game; invalid input is rejected with a reason.
3. **Previous** / **Next** (`Ctrl+P` / `Ctrl+N`) browse games; **Change** (`Ctrl+E`) overwrites the shown game; **Delete** removes it.
4. **Ranking** shows standings (with wins and best round; `=` marks a shared rank).
5. **Present** launches the presentation program for this tournament.
6. **Export HTML** renders `docs/index.html` locally. See [Publishing results to GitHub Pages](#publishing-results-to-github-pages).

---

## Graph presentation window

The presentation cycles through four pages:

| Page | Description |
|---|---|
| **Splash** | "Café Pony" logo with animated fade-in and fade-out. |
| **Ranking** | Players revealed one by one from last place to first, with medals for the top 3. |
| **Compare** | Matplotlib line chart of cumulative points over rounds. Toggle players in the left sidebar. |
| **Walter** | Special advert page with a pixel-trickle wipe transition. |

### Keyboard shortcuts

| Key | Action |
|---|---|
| `Space` | Reveal the next hidden ranking row (manual mode) |
| `A` | Toggle auto mode on / off |
| `W` | Toggle the Walter advert page |
| `←` / `→` | Step backward / forward through pages |
| `F` / `F11` | Toggle fullscreen |
| `Escape` | Exit fullscreen |

### Navigation buttons

Every page has **Logo**, **Compare**, and **Ranking** buttons in the header bar. Clicking **Ranking** while already on the ranking page reveals the next row (same as `Space`).

### Auto mode

Auto mode cycles through three stages continuously:

1. **Logo** — the "Café Pony" title fades in and out.
2. **Walter** — the Walter advert is shown, then wiped away with a pixel-trickle effect.
3. **Compare** — two players are selected at random and shown on the comparison graph.

Interacting with the compare graph while auto mode has ever been started will pause auto mode and schedule an automatic resume after `--auto-resume` seconds (shown as "(autoresume)" under the Auto button).

Clicking the logo or Walter advert while auto mode is running skips the current stage immediately.

---

## Publishing results to GitHub Pages

`scripts/export_html.py` renders the highest-numbered tournament with a `ranking.csv` into a standalone HTML results page. It has no PyQt dependency, so it can also run headless in CI.

`.github/workflows/pages.yml` rebuilds and deploys that page automatically: on every push to `main` that touches a `ranking.csv`, it regenerates `docs/index.html` and publishes it via GitHub Pages. `docs/` itself is gitignored — it's a build artifact, never committed.

**One-time setup:** in the repo's GitHub settings, go to **Settings → Pages** and set **Build and deployment → Source** to **GitHub Actions**.

**Ongoing use:** after entering results, commit and push the updated `tournaments/<N>/*.csv` — the site rebuilds automatically. Use the **Export HTML** button to preview the page locally first.

---

## Building executables

```bash
./build.sh     # PyInstaller -> dist/tarockmanager and dist/presenter
```
(The frozen builds are untested; `tarock_core/paths.py` locates the repo relative to the source files.)
