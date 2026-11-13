"""Offline HTML overview across several tournaments ("Saison").

Standalone and read-only: reads tournaments/<N>/player_numbers.csv + result.csv,
writes one self-contained HTML file (no internet needed). Changes nothing else.

    python scripts/season_overview.py              # tournaments 15, 16, 17
    python scripts/season_overview.py 15 16 17 18  # any selection
    python scripts/season_overview.py -o saison.html

Players are matched across tournaments by name (case-insensitive), with the
aliases below. Names in EXCLUDE are left out of the overview entirely.
"""
from __future__ import annotations

import argparse
import html
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tarock_core import csv_io, ranking  # noqa: E402  (read-only use)

DEFAULT_TOURNAMENTS = [15, 16, 17]
ALIASES = {"ronni": "Ronny"}           # spelling variant -> canonical name
EXCLUDE = {"roland/gerald"}            # shared seats: not counted


@dataclass
class Result:                          # one player in one tournament
    rank: int
    tied: bool
    total: int
    wins: int
    best_round: int
    field_size: int


@dataclass
class Player:
    name: str
    results: dict[int, Result] = field(default_factory=dict)

    @property
    def played(self) -> int:
        return len(self.results)

    @property
    def total(self) -> int:
        return sum(r.total for r in self.results.values())

    @property
    def wins(self) -> int:
        return sum(r.wins for r in self.results.values())

    @property
    def titles(self) -> int:
        return sum(1 for r in self.results.values() if r.rank == 1)

    @property
    def podiums(self) -> int:
        return sum(1 for r in self.results.values() if r.rank <= 3)

    @property
    def avg_points(self) -> float:
        return self.total / self.played

    @property
    def avg_rank(self) -> float:
        return sum(r.rank for r in self.results.values()) / self.played

    @property
    def best_round(self) -> int:
        return max(r.best_round for r in self.results.values())


def canonical(name: str) -> str | None:
    key = name.strip().casefold()
    if key in EXCLUDE:
        return None
    return ALIASES.get(key, name.strip())


def load(tournaments: list[int]) -> tuple[list[int], list[int], dict[str, Player]]:
    """Returns (tournaments with results, tournaments without results, players by key)."""
    played, pending = [], []
    players: dict[str, Player] = {}
    for t in tournaments:
        folder = ROOT / "tournaments" / str(t)
        if not folder.is_dir():
            sys.exit(f"Turnier {t}: Ordner {folder} fehlt")
        try:
            parsed = csv_io.parse_tournament(folder)
        except csv_io.ImportErrors as e:
            sys.exit(f"Turnier {t}: CSV-Dateien nicht lesbar:\n  " + "\n  ".join(e.errors))
        if not parsed.games:
            pending.append(t)
            continue
        played.append(t)
        standings = ranking.compute(list(parsed.games), parsed.players)
        size = len(standings.rows)
        for s in standings.rows:
            name = canonical(s.name)
            if name is None:
                continue
            p = players.setdefault(name.casefold(), Player(name))
            p.results[t] = Result(s.rank, s.tied, s.total, s.wins, s.best_round, size)
    return played, pending, players


def overall_order(players: dict[str, Player]) -> list[tuple[int, Player]]:
    """Ranked by total points, then tournament wins, then table wins; equal = shared rank."""
    def key(p: Player) -> tuple:
        return (-p.total, -p.titles, -p.wins)
    rows = sorted(players.values(), key=lambda p: (key(p), p.name.casefold()))
    return [(1 + sum(1 for q in rows if key(q) < key(p)), p) for p in rows]


# ------------------------------------------------------------------ HTML ----
MEDAL = {1: "🥇", 2: "🥈", 3: "🥉"}
e = html.escape


def fmt_signed(n: float, digits: int = 0) -> str:
    s = f"{n:+.{digits}f}".replace(".", ",")
    return s.replace("-", "−")


def rank_cell(r: Result | None) -> str:
    if r is None:
        return '<td class="na" data-v="999">–</td>'
    label = f"{r.rank}." + (" " + MEDAL[r.rank] if r.rank in MEDAL else "")
    tip = f"{r.total:+d} Punkte, Platz {r.rank} von {r.field_size}" + (" (geteilt)" if r.tied else "")
    return f'<td class="num" data-v="{r.rank}" title="{e(tip)}">{label}<span class="sub">{fmt_signed(r.total)}</span></td>'


def bar_chart(ranked: list[tuple[int, Player]]) -> str:
    rows = [p for _, p in ranked]
    lim = max(1, max(abs(p.total) for p in rows))
    row_h, label_w, val_w, width = 26, 120, 56, 760
    plot_w = width - label_w - val_w * 2
    zero = label_w + val_w + plot_w / 2
    scale = (plot_w / 2) / lim
    height = row_h * len(rows) + 8
    parts = [f'<svg viewBox="0 0 {width} {height}" class="bars" role="img" aria-label="Gesamtpunkte">',
             f'<line x1="{zero}" y1="0" x2="{zero}" y2="{height}" class="axis"/>']
    for i, p in enumerate(rows):
        y = 4 + i * row_h
        w = abs(p.total) * scale
        x = zero if p.total >= 0 else zero - w
        cls = "pos" if p.total >= 0 else "neg"
        parts.append(f'<text x="{label_w - 8}" y="{y + row_h / 2 + 5}" class="lbl" text-anchor="end">{e(p.name)}</text>')
        parts.append(f'<rect x="{x:.1f}" y="{y + 4}" width="{max(w, 1.5):.1f}" height="{row_h - 8}" rx="4" class="{cls}">'
                     f'<title>{e(p.name)}: {p.total:+d}</title></rect>')
        if p.total >= 0:
            parts.append(f'<text x="{x + w + 6:.1f}" y="{y + row_h / 2 + 5}" class="val">{fmt_signed(p.total)}</text>')
        else:
            parts.append(f'<text x="{x - 6:.1f}" y="{y + row_h / 2 + 5}" class="val" text-anchor="end">{fmt_signed(p.total)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def highlights(played: list[int], players: dict[str, Player]) -> str:
    cards = []
    allp = list(players.values())

    def card(title: str, value: str, who: str) -> None:
        cards.append(f'<div class="card"><div class="ct">{e(title)}</div>'
                     f'<div class="cv">{value}</div><div class="cw">{who}</div></div>')

    def names(ps: list[Player]) -> str:
        return ", ".join(e(p.name) for p in ps)

    best_t = max(r.total for p in allp for r in p.results.values())
    who = [f"{e(p.name)} (Turnier {t})" for p in allp for t, r in sorted(p.results.items()) if r.total == best_t]
    card("Beste Turnierleistung", fmt_signed(best_t), ", ".join(who))

    best_r = max(p.best_round for p in allp)
    card("Beste einzelne Runde", fmt_signed(best_r), names([p for p in allp if p.best_round == best_r]))

    most_w = max(p.wins for p in allp)
    card("Meiste Tischsiege", str(most_w), names([p for p in allp if p.wins == most_w]))

    if len(played) > 1:
        always = sorted((p for p in allp if p.played == len(played)), key=lambda p: p.name.casefold())
        if always:
            card(f"Bei allen {len(played)} Turnieren dabei", str(len(always)), names(always))
        regulars = [p for p in allp if p.played >= 2]
        if regulars:
            best_avg = min(p.avg_rank for p in regulars)
            card("Bester Ø-Platz (ab 2 Turnieren)", f"{best_avg:.1f}".replace(".", ","),
                 names([p for p in regulars if p.avg_rank == best_avg]))
    return '<div class="cards">' + "".join(cards) + "</div>"


def podiums(played: list[int], players: dict[str, Player]) -> str:
    out = []
    for t in played:
        entries = sorted(((r.rank, p.name, r.total) for p in players.values()
                          for tt, r in p.results.items() if tt == t and r.rank <= 3))
        li = "".join(f'<li><span class="m">{MEDAL[rk]}</span>{e(n)}<span class="pts">{fmt_signed(tot)}</span></li>'
                     for rk, n, tot in entries)
        out.append(f'<div class="pod"><h3>Turnier {t}</h3><ul>{li}</ul></div>')
    return '<div class="pods">' + "".join(out) + "</div>"


def table(played: list[int], ranked: list[tuple[int, Player]]) -> str:
    sizes = {t: next((r.field_size for _, p in ranked for tt, r in p.results.items() if tt == t), 0) for t in played}
    head = ['<th data-t="n">#</th>', '<th data-t="s" class="l">Name</th>']
    head += [f'<th data-t="n" title="{sizes[t]} Spieler">T{t}</th>' for t in played]
    head += ['<th data-t="n">Teiln.</th>', '<th data-t="n">Punkte</th>', '<th data-t="n">Ø Punkte</th>',
             '<th data-t="n">Ø Platz</th>', '<th data-t="n">Siege</th>', '<th data-t="n">Podest</th>',
             '<th data-t="n">Tischsiege</th>']
    body = []
    shared = {rk for rk, _ in ranked if sum(1 for r2, _ in ranked if r2 == rk) > 1}
    for rk, p in ranked:
        cells = [f'<td class="num" data-v="{rk}">{rk}{"=" if rk in shared else ""}</td>',
                 f'<td class="l name" data-v="{e(p.name.casefold())}">{e(p.name)}</td>']
        cells += [rank_cell(p.results.get(t)) for t in played]
        cells += [f'<td class="num" data-v="{p.played}">{p.played}</td>',
                  f'<td class="num strong {"pos" if p.total >= 0 else "neg"}t" data-v="{p.total}">{fmt_signed(p.total)}</td>',
                  f'<td class="num" data-v="{p.avg_points:.3f}">{fmt_signed(p.avg_points, 1)}</td>',
                  f'<td class="num" data-v="{p.avg_rank:.3f}">{f"{p.avg_rank:.1f}".replace(".", ",")}</td>',
                  f'<td class="num" data-v="{p.titles}">{p.titles or ""}</td>',
                  f'<td class="num" data-v="{p.podiums}">{p.podiums or ""}</td>',
                  f'<td class="num" data-v="{p.wins}">{p.wins}</td>']
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (f'<div class="tw"><table id="t"><thead><tr>{"".join(head)}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


CSS = """
:root{--bg:#f6f4ef;--panel:#fff;--ink:#1d1f24;--mute:#6b6f78;--line:#e4e1d8;--accent:#8a1c2b;
--pos:#2f7d4f;--neg:#b5453a;--hl:#faf3e3}
@media (prefers-color-scheme:dark){:root{--bg:#15171b;--panel:#1e2127;--ink:#eceae4;--mute:#9a9ea8;
--line:#2e323a;--accent:#e0707e;--pos:#5cbf86;--neg:#e2766a;--hl:#2a2620}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:28px 16px 60px}
header h1{margin:0;font-size:2.2rem;letter-spacing:-.02em}
header h1 span{color:var(--accent)}
header p{margin:.3rem 0 0;color:var(--mute)}
h2{font-size:1.25rem;margin:2.2rem 0 .8rem}
.note{background:var(--hl);border:1px solid var(--line);border-radius:10px;padding:.6rem .9rem;margin-top:1rem}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.ct{color:var(--mute);font-size:.85rem}
.cv{font-size:1.8rem;font-weight:700;font-variant-numeric:tabular-nums;margin:.1rem 0}
.cw{font-size:.95rem}
.pods{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
.pod{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 16px}
.pod h3{margin:0 0 .4rem;font-size:1rem;color:var(--accent)}
.pod ul{list-style:none;margin:0;padding:0}
.pod li{display:flex;align-items:center;gap:.5rem;padding:.15rem 0}
.pod .m{width:1.6rem}.pod .pts{margin-left:auto;color:var(--mute);font-variant-numeric:tabular-nums}
.tw{overflow-x:auto;background:var(--panel);border:1px solid var(--line);border-radius:12px}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{padding:.5rem .6rem;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th{font-size:.8rem;color:var(--mute);font-weight:600;cursor:pointer;user-select:none;position:sticky;top:0;background:var(--panel)}
th:hover{color:var(--ink)}
th.asc::after{content:" ▲"}th.desc::after{content:" ▼"}
.l{text-align:left}.name{font-weight:600}
tbody tr:hover{background:var(--hl)}
td.na{color:var(--mute);text-align:center}
.sub{display:block;font-size:.75rem;color:var(--mute)}
.strong{font-weight:700}.post{color:var(--pos)}.negt{color:var(--neg)}
.bars{width:100%;height:auto;background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:8px}
.bars .axis{stroke:var(--line);stroke-width:1.5}
.bars .pos{fill:var(--pos)}.bars .neg{fill:var(--neg)}
.bars .lbl{fill:var(--ink);font-size:13px}.bars .val{fill:var(--mute);font-size:12px;font-variant-numeric:tabular-nums}
footer{margin-top:2.5rem;color:var(--mute);font-size:.85rem}
"""

JS = """
document.querySelectorAll('#t th').forEach((th,i)=>th.addEventListener('click',()=>{
 const tb=document.querySelector('#t tbody'),rows=[...tb.rows],num=th.dataset.t==='n';
 const asc=!th.classList.contains('asc');
 document.querySelectorAll('#t th').forEach(h=>h.classList.remove('asc','desc'));
 th.classList.add(asc?'asc':'desc');
 rows.sort((a,b)=>{let x=a.cells[i].dataset.v,y=b.cells[i].dataset.v;
  if(num){x=parseFloat(x);y=parseFloat(y);return asc?x-y:y-x}
  return asc?x.localeCompare(y):y.localeCompare(x)});
 rows.forEach(r=>tb.appendChild(r));
}));
"""


def render(played: list[int], pending: list[int], players: dict[str, Player]) -> str:
    ranked = overall_order(players)
    span = f"{played[0]}–{played[-1]}" if len(played) > 1 else str(played[0])
    note = ""
    if pending:
        note = f'<div class="note">Noch keine Ergebnisse: Turnier {", ".join(map(str, pending))}.</div>'
    return f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Café Pony Turnierübersicht</title><style>{CSS}</style></head>
<body><main>
<header><h1>Café Pony <span>Turnierübersicht</span></h1>
<p>Turniere {e(span)} · {len(players)} Spieler · Stand {datetime.now():%d.%m.%Y %H:%M}</p>{note}</header>
<h2>Highlights</h2>{highlights(played, players)}
<h2>Turniersieger</h2>{podiums(played, players)}
<h2>Gesamtwertung</h2>
<p style="color:var(--mute);margin-top:-.4rem">Sortiert nach Gesamtpunkten (dann Turniersiege, Tischsiege).
Spalten anklicken zum Umsortieren. Unter jeder Platzierung stehen die Punkte in dem Turnier.</p>
{table(played, ranked)}
<h2>Gesamtpunkte</h2>{bar_chart(ranked)}
<footer>Platzierungen pro Turnier nach den Turnierregeln (Punkte, Tischsiege, beste Runde).
„–“ = nicht teilgenommen.</footer>
</main><script>{JS}</script></body></html>
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tournaments", nargs="*", type=int, default=DEFAULT_TOURNAMENTS)
    ap.add_argument("-o", "--output", type=Path, default=ROOT / "docs" / "saison.html")
    args = ap.parse_args()

    played, pending, players = load(args.tournaments)
    if not played:
        sys.exit("Keines der Turniere hat Ergebnisse.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(played, pending, players), encoding="utf-8")

    print(f"Turniere mit Ergebnissen: {played}" + (f", noch ohne: {pending}" if pending else ""))
    print(f"{len(players)} Spieler")
    for rk, p in overall_order(players)[:5]:
        print(f"  {rk:>2}. {p.name:<12} {p.total:+5d}  ({p.played} Turniere)")
    print(f"Geschrieben: {args.output}")


if __name__ == "__main__":
    main()
