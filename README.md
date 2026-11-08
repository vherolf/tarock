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

Two separate programs share one SQLite database (`tournaments/tournaments.db`), which is a **working copy** of the
CSV files in `tournaments/<N>/`:

| Program | Role | Database access |
|---|---|---|
| `tarockmanager.py` | Data entry: players, table results, ranking view | read / write |
| `presenter.py` + `tarock_presenter/` | Animated results presentation (entry point + window code) | **read-only** (SQLite rejects any write) |
| `tarock_core/` | Shared, Qt-free code: schema + validation (`db.py`), ranking rules (`ranking.py`), CSV import/export (`csv_io.py`), HTML export, the entry tool's HTML views (`html_views.py`), consistency check | - |

### The CSV files are the master copy
`tournaments/<N>/result.csv` and `player_numbers.csv` are the truth: readable, versioned in git, and portable between
machines. The SQLite database enforces the rules and feeds the presenter live, but it can be **deleted at any time** - it is
rebuilt from the CSV files. `ranking.csv` is derived (always recomputed) and never read back as data.

- **Every save writes both, as one step.** The database change and the CSV export happen in one transaction. If the CSV files
  cannot be written (disk full, read-only folder) the change is rolled back and the status says "NOT saved" - the two can never disagree.
- **On start, the data-entry tool synchronises the tournament it opens:**
  - database missing, empty or without that tournament -> it is rebuilt from the CSV files;
  - database holds *different* data -> the CSV files win; the whole database is first copied to `tournaments/backups/`
    (the newest 20 are kept) and a dialog tells you where;
  - database already matches -> nothing is written;
  - no CSV files yet but the database has data -> the CSV files are created from it;
  - CSV files unreadable or breaking a rule, or only one of the two data files exists -> the tool refuses to open that
    tournament, lists the problems and changes nothing (so a broken file is never overwritten by the next save);
  - a stale `ranking.csv` is regenerated (it is derived data).
- **The presenter never writes.** With no database it stops with a message telling you to start the data-entry tool once
  (which rebuilds it). If the CSV files differ from the database it shows a warning. `python scripts/rebuild_db.py`
  rebuilds all tournaments at once (`--dry-run` only reports).
- **Commit the CSV files** - they are the only copy that is backed up. (The database and `tournaments/backups/` are gitignored.)

### Data integrity
- Only registered players can score, a player sits at one table per round, a table is used once per round, every game has exactly 4 players and its points sum to 0. These are checked in the app *and* enforced by the schema (foreign keys, UNIQUE, CHECK).
- Every write is one transaction: a rejected change leaves the old data untouched.
- The tools audit the data on start-up and warn about inconsistencies; CI checks the committed CSV files before publishing.

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
| `--compare-seconds SEC` | | `20` | How long auto mode shows the player comparison. Multiplied by `--speed-auto-mode` like every auto-mode time. |
| `--auto-stages LIST` | | `logo,compare` | Stages auto mode cycles through, from `logo`, `walter`, `compare` (e.g. `logo,walter,compare`). |

The presentation updates live: it polls the database (about once a second) and rebuilds the ranking and compare pages when the entry tool saves, keeping the current page, the revealed rows and the selected players. It never writes to the database.

### Test tournaments 0 and 1

Every start of `tarockmanager.py` regenerates two throw-away tournaments, so there is always fresh data to try things out on:
**tournament 0** (14 players, 3 tables per round, 2 players sit out each round) and **tournament 1** (16 players, 4 tables), 6 rounds each.
Whatever you deleted or changed in them while testing is gone at the next start. Open them with `-t 0` / `-t 1`.

| Argument | Description |
|---|---|
| `--no-test-data` | Do not regenerate them (e.g. to keep what you did in them). |
| `--test-seed N` | Use this seed instead of a random one. The seed is printed at start-up, so a data set can be reproduced. |

The generated folders `tournaments/0/` and `tournaments/1/` are gitignored and never published. Other tournaments are never touched.
The presenter does not generate anything (it is read-only) - start the data-entry tool once to create them.

### Rebuilding the database from the CSV files

```bash
python scripts/rebuild_db.py [N ...] [--dry-run]
```
Use it after deleting the database or after a `git clone` / `git pull`. A tournament whose database content differs is replaced
by its CSV files (after a backup); invalid CSV files are listed and change nothing.

### Tests

```bash
python -m pytest tests     # ~12 s; GUI tests run headless (Qt offscreen platform)
```

The rules are kept out of the GUI so they can be tested: ranking and database rules and the entry tool's HTML views (`tarock_core`), the auto-mode state machine
(`tarock_presenter/automode.py`) and the display data (`tarock_presenter/viewmodel.py`) are plain Python; both windows (entry tool and presenter) are covered by headless GUI tests.

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
2. **Compare** — three players are shown on the comparison graph: one of the winners (ranks 1-3) as the anchor plus two other players chosen at random. It stays for 20 seconds by default (`--compare-seconds`, scaled by `--speed-auto-mode`).

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
