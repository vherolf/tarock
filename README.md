# Tarock Tournament Manager

A PyQt6 desktop application for recording and managing 4-player Tarock tournament results. Tracks per-table scores across rounds, computes rankings, and drives an animated results presentation with comparison graphs.

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

## Running

```bash
python tarockmanager.py
```

### Command-line arguments

| Argument | Short | Type | Default | Description |
|---|---|---|---|---|
| `--tournament N` | `-t` | integer | latest | Tournament number to open (e.g. `--tournament 13`). Opens the highest-numbered tournament folder if omitted. A new folder is created automatically if it does not exist. |
| `--speed-auto-mode X` | `-s` | float | `1.0` | Auto-mode speed multiplier. `0.5` is twice as fast, `2.0` is twice as slow. Scales all timed transitions (logo fade, ranking hold, compare hold, Walter hold). |
| `--auto-resume SEC` | `-r` | integer | `180` | Seconds of inactivity on the compare page before auto mode resumes automatically. |

**Examples**

```bash
# Open tournament 13
python tarockmanager.py --tournament 13

# Open the latest tournament at double speed
python tarockmanager.py -s 0.5

# Open tournament 5, slow auto mode, 60 s auto-resume
python tarockmanager.py -t 5 -s 2.0 -r 60
```

---

## Data layout

Each tournament stores its data in `tournaments/<N>/`:

| File | Contents |
|---|---|
| `result.csv` | Raw game entries — table, round, and the four players' numbers and points |
| `player_numbers.csv` | Player-number → name mapping |
| `ranking.csv` | Computed standings (written by **Sum / Rank**) |

---

## Usage

### Player mapping (left panel)

Fill in player numbers and names, then click **Save Mapping**. This writes `player_numbers.csv` into the tournament folder and is used to display names throughout the application. Click **Load Mapping** to reload from disk.

### Recording results (right panel)

1. Set the **Round** number and **Table Number**.
2. Enter the **Player Number** and **Points** for each of the 4 players at the table. Points must sum to zero.
3. Click **Submit** (`Ctrl+S`) to save the entry.
   - A table already submitted for the same round cannot be submitted again — use **Change** to correct it.
4. Use **Previous** (`Ctrl+P`) and **Next** (`Ctrl+N`) to browse existing entries.
5. **Change** (`Ctrl+E`) overwrites the currently displayed entry.
6. **Delete** removes the current entry (with confirmation).
7. **Sum / Rank** computes overall standings and saves them to `ranking.csv`.
8. **Graph** opens the animated results presentation window.
9. **Export HTML** renders the latest tournament's `ranking.csv` into a standalone results page at `docs/index.html` for local preview. See [Publishing results to GitHub Pages](#publishing-results-to-github-pages).

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

**Ongoing use:** after running **Sum / Rank**, commit and push the updated `ranking.csv` — the site rebuilds automatically. Use the **Export HTML** button to preview the page locally first.

---

## Building an executable

The project uses [cx_Freeze](https://cx-freeze.readthedocs.io/) to produce a standalone executable.

```bash
# Install dependencies (including cx_Freeze)
pip install -r requirements.txt

# Build
python setup.py build
```

The compiled executable is placed in the `build/` folder. On Windows the application runs without a console window.
