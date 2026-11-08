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
| `presenter.py` + `tarock_presenter/` | Animated results presentation (entry point + window code) | **read-only** (SQLite rejects any write) |
| `tarock_core/` | Shared, Qt-free code: schema + validation (`db.py`), ranking rules (`ranking.py`), CSV import/export (`csv_io.py`), HTML export, consistency check | - |

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
| `--auto-stages LIST` | | `logo,compare` | Stages auto mode cycles through, from `logo`, `walter`, `compare` (e.g. `logo,walter,compare`). |

The presentation updates live: it polls the database (about once a second) and rebuilds the ranking and compare pages when the entry tool saves, keeping the current page, the revealed rows and the selected players. It never writes to the database.

### Importing legacy CSV data

```bash
python scripts/import_csv.py [N ...] [--compare]
```
Validates every row and imports each tournament all-or-nothing. Invalid rows are listed, never skipped silently.

### Tests

```bash
python -m pytest tests     # ~12 s; GUI tests run headless (Qt offscreen platform)
```

The rules are kept out of the GUI so they can be tested: ranking and database rules (`tarock_core`), the auto-mode state machine
(`tarock_presenter/automode.py`) and the display data (`tarock_presenter/viewmodel.py`) are plain Python; the window itself is covered by headless GUI tests.

---

## Usage (data entry)

### Player mapping (left panel)
Fill in numbers and names, then **Save Mapping**. Names must be unique; a player who already has results cannot be removed.

### Recording results (right panel)
1. Set **Round** and **Table Number**, then the 4 player numbers (must be in the mapping) and points (must sum to 0).
2. **Submit** (`Ctrl+S`) stores the game; invalid input is rejected with a reason. If the round/table already has a result, a warning asks whether to overwrite it (the default answer keeps the existing result).
3. **Previous** / **Next** (`Ctrl+P` / `Ctrl+N`) browse games; **Delete** removes the shown game. To correct a game, edit it and press **Submit** again.
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

Auto mode cycles through its stages continuously. By default these are two (change them with `--auto-stages`):

1. **Logo** — the "Café Pony" title fades in and out.
2. **Compare** — two players are selected at random and shown on the comparison graph.

The optional **Walter** stage shows the Walter advert and then wipes it away with a pixel-trickle effect
(`--auto-stages logo,walter,compare`). The advert is always available manually with the `W` key.

Interacting with the compare graph (selecting a player, clicking the chart) after auto mode has been started pauses it and
schedules an automatic resume after `--auto-resume` seconds (shown as "(autoresume)" under the Auto button).
Navigating manually (buttons, arrow keys, `W`) stops auto mode without a resume.

Clicking the logo or Walter advert while auto mode is running skips to the next stage immediately.

---

## Publishing results to GitHub Pages

Publishing is explicit: the page shows the tournament named in **`tournaments/published.txt`** (a file containing just
the number, e.g. `16`). Newer or test tournaments are never published by accident, and without the file nothing is built.

`.github/workflows/pages.yml` runs on every push to `main` that touches `tournaments/**`, `tarock_core/**` or the scripts:

1. `scripts/check_data.py` verifies that the committed CSVs are consistent: every tournament's `result.csv` +
   `player_numbers.csv` must pass all database rules, and `ranking.csv` must equal the ranking computed from `result.csv`
   (not stale, not edited by hand). A failure stops the deployment.
2. `scripts/export_html.py` renders the published tournament to `docs/index.html` and it is deployed. `docs/` is
   gitignored - a build artifact.

**One-time setup:** in the repo's GitHub settings, go to **Settings -> Pages** and set **Build and deployment -> Source** to **GitHub Actions**.

**Ongoing use:** enter results (the CSV copies in `tournaments/<N>/` update on every save), then commit and push them.
To publish a different tournament, change the number in `tournaments/published.txt`. Run `python scripts/check_data.py`
locally to see what CI will check. The **Export HTML** button renders the *current* tournament to `docs/index.html` as a local preview.

---

## Building executables

```bash
./build.sh     # PyInstaller -> dist/tarockmanager and dist/presenter
```
Keep both executables in the same folder: **Present** starts `presenter` from next to `tarockmanager`.
The `tournaments/` folder (database and CSVs) and `docs/` are read and written next to the executables, while
`images/` is bundled inside `presenter`. The frozen builds are covered by unit tests of the path logic but have not been run end to end.
