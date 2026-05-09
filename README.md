# Tarock Tournament Manager

A PyQt6 desktop application for recording and managing 4-player Tarock tournament results. Tracks per-table scores, computes rankings, and displays an animated results presentation with comparison graphs.

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

### Command-line parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `--tournament N` | integer | latest | Tournament number to open (e.g. `--tournament 3`). Opens the highest-numbered tournament folder if omitted. A new folder is created automatically if it does not exist. |
| `--speed X` | float | `1.0` | Timer speed multiplier for the graph presentation. `0.5` is twice as fast, `2.0` is twice as slow. |

**Examples**

```bash
# Open tournament number 5
python tarockmanager.py --tournament 5

# Open the latest tournament at double speed
python tarockmanager.py --speed 0.5

# Open tournament 2 at half speed
python tarockmanager.py --tournament 2 --speed 2.0
```

---

## Usage

### Player mapping (left panel)

Fill in player numbers and names, then click **Save Mapping**. This writes `player_numbers.csv` inside the tournament folder and is used to display names throughout the application.

### Recording results (right panel)

1. Set the **Round** number and **Table Number**.
2. Enter the **Player Number** and **Points** for each of the 4 players at the table.
3. Click **Submit** (or `Ctrl+S`) to save the entry.
   - A table that has already been submitted for the same round cannot be submitted again — use **Change** to correct it.
4. Use **Previous** (`Ctrl+P`) and **Next** (`Ctrl+N`) to browse existing entries.
5. **Change** (`Ctrl+E`) overwrites the currently displayed entry.
6. **Delete** removes the current entry (with confirmation).
7. **Sum / Rank** computes the overall standings and saves them to `ranking.csv`.
8. **Graph** opens the animated results presentation window.

### Graph presentation window

The graph window cycles through three stages:

1. **Splash** — animated "Cafe Pony" title screen.
2. **Ranking** — players revealed one by one from last place to first, with medals for the top 3.
3. **Comparison graph** — a matplotlib line chart comparing cumulative points over rounds.

**Controls**

| Key / Button | Action |
|---|---|
| `Space` / **Auto** | Toggle auto-advance mode |
| `←` / `▶` | Step backward / forward manually |
| **Compare** | Jump directly to the comparison graph |
| `F11` | Toggle fullscreen |
| `Escape` | Exit fullscreen |

In auto mode the ranking rows are revealed at 0.1 s intervals, followed by a 10 s pause before the comparison graph is shown. When the comparison graph is reached automatically, two players are selected at random for comparison. Clicking a player button in the sidebar toggles them in/out of the comparison and pauses auto mode.

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

> **Note:** Make sure `player_numbers.csv` and `result.csv` exist in the project root before building, as they are bundled into the executable by `setup.py`.
