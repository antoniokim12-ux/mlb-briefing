#!/usr/bin/env python3
"""
MLB Daily Briefing — card renderer
==================================

Turns a slate_YYYY-MM-DD.json (produced by mlb_briefing.py) into a
self-contained HTML page you double-click to open. No server, no JavaScript
for layout — the expandable "Why" uses native <details>, so it just works.

USAGE
-----
  python render_cards.py                       # newest slate_*.json in this folder
  python render_cards.py slate_2026-06-14.json # a specific file
  # then open the slate_YYYY-MM-DD.html it writes (double-click it)
"""

import datetime as dt
import glob
import html
import json
import os
import sys

# Design tokens — shared with the on-screen card concept.
CSS = """
@import url('https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700&family=Archivo+Narrow:wght@500;600;700&family=JetBrains+Mono:wght@500;700&display=swap');
:root{--ink:#0C1418;--panel:#13202A;--panel2:#0F1A22;--line:#24333D;--bone:#E9E6DC;--muted:#8A9AA3;--amber:#F2B53B;--turf:#46B47A;--clay:#E2603E;--steel:#6FA8C7;}
*{box-sizing:border-box;}
body{background:var(--ink);color:var(--bone);font-family:'Archivo',system-ui,sans-serif;margin:0;padding:28px 16px 56px;}
.wrap{max-width:760px;margin:0 auto;}
.eyebrow{font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.22em;text-transform:uppercase;color:var(--amber);}
h1{font-family:'Archivo Narrow',sans-serif;font-weight:700;font-size:34px;letter-spacing:.01em;margin:6px 0 4px;}
.sub{color:var(--muted);font-size:14px;max-width:60ch;line-height:1.5;}
.note{margin:18px 0 26px;border:1px solid var(--line);border-left:3px solid var(--amber);background:var(--panel2);padding:13px 15px;border-radius:6px;font-size:12.5px;color:#C7CFD3;line-height:1.55;}
.note b{color:var(--bone);}
.card{border:1px solid var(--line);background:var(--panel);border-radius:10px;margin-bottom:16px;overflow:hidden;}
.head{display:flex;}
.side{flex:1;padding:14px 16px;}
.side.away{border-right:1px solid var(--line);}
.team{font-family:'Archivo Narrow',sans-serif;font-weight:700;font-size:20px;letter-spacing:.02em;}
.rec{color:var(--muted);font-size:11.5px;font-family:'JetBrains Mono',monospace;margin-top:1px;}
.pit{color:var(--steel);font-size:11.5px;font-family:'JetBrains Mono',monospace;margin-top:5px;}
.oddsrow{display:flex;align-items:baseline;gap:8px;margin-top:8px;}
.ml{font-family:'JetBrains Mono',monospace;font-weight:700;font-size:18px;color:var(--amber);}
.imp{font-size:11px;color:var(--muted);font-family:'JetBrains Mono',monospace;}
.bar{height:7px;display:flex;border-top:1px solid var(--line);}
.bar i{display:block;height:100%;}
.meta{display:flex;gap:14px;flex-wrap:wrap;padding:10px 16px;background:var(--panel2);border-top:1px solid var(--line);font-size:11.5px;color:var(--muted);font-family:'JetBrains Mono',monospace;}
.meta b{color:var(--steel);font-weight:500;}
.body{padding:13px 16px 16px;}
.leanrow{display:flex;align-items:center;gap:10px;}
.pill{font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;padding:4px 9px;border-radius:4px;}
.dots{display:flex;gap:3px;}
.dot{width:7px;height:7px;border-radius:50%;background:var(--line);}
.dot.on{background:var(--turf);}
.dlabel{font-size:11.5px;color:var(--muted);}
.vnote{margin-top:11px;font-size:12.5px;line-height:1.5;color:#C7CFD3;}
.vnote.val{color:var(--bone);}
.vnote b{color:var(--amber);}
details{margin-top:13px;}
summary{list-style:none;cursor:pointer;display:inline-flex;align-items:center;gap:7px;border:1px solid var(--line);color:var(--bone);font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.06em;text-transform:uppercase;padding:6px 11px;border-radius:5px;}
summary::-webkit-details-marker{display:none;}
summary::marker{content:"";}
summary::before{content:"\\25B8";display:inline-block;transition:transform .15s;color:var(--muted);}
details[open] summary::before{transform:rotate(90deg);}
summary:hover{border-color:var(--amber);color:var(--amber);}
.factors{border-top:1px dashed var(--line);margin-top:13px;padding-top:13px;display:grid;gap:9px;}
.f{display:grid;grid-template-columns:30px 1fr;gap:10px;align-items:start;font-size:13px;line-height:1.45;}
.fmark{font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;text-align:center;border-radius:3px;padding:1px 0;background:rgba(0,0,0,.25);}
.flabel{color:var(--muted);font-weight:600;}
.read{margin-top:13px;padding:12px 14px;background:var(--panel2);border:1px solid var(--line);border-radius:7px;font-size:13px;line-height:1.6;color:#D4D9DB;}
.read b{color:var(--amber);font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.1em;text-transform:uppercase;display:block;margin-bottom:5px;}
.pick{margin:0 0 22px;border:1px solid var(--amber);background:linear-gradient(180deg,rgba(242,181,59,.10),rgba(242,181,59,.03));border-radius:10px;padding:16px 18px;}
.pick .lab{font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--amber);}
.pick .team{font-family:'Archivo Narrow',sans-serif;font-weight:700;font-size:26px;margin:6px 0 2px;}
.pick .team .ml{font-family:'JetBrains Mono',monospace;font-size:18px;color:var(--amber);margin-left:9px;}
.pick .why{font-size:13px;color:#D4D9DB;line-height:1.55;margin-top:6px;}
.pick.none{border-color:var(--line);background:var(--panel2);}
.pick.none .lab{color:var(--muted);}
.scoreboard{display:flex;flex-wrap:wrap;gap:7px 16px;align-items:center;margin:0 0 16px;padding:9px 14px;border:1px solid var(--line);border-radius:8px;background:var(--panel2);font-family:'JetBrains Mono',monospace;font-size:12px;}
.sb-lab{color:var(--amber);letter-spacing:.16em;text-transform:uppercase;font-size:10.5px;}
.sb-stat{color:var(--bone);}
.sb-stat b{color:var(--muted);font-weight:500;}
.lines{border-top:1px dashed var(--line);margin-top:13px;padding-top:12px;}
.lines-h{font-family:'JetBrains Mono',monospace;font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);margin-bottom:8px;}
.line-row{display:flex;justify-content:space-between;align-items:baseline;gap:12px;font-size:13px;}
.line-name{font-family:'Archivo Narrow',sans-serif;font-weight:600;}
.line-odds{font-family:'JetBrains Mono',monospace;color:var(--amber);font-size:12px;}
.line-read{font-size:12px;color:var(--muted);line-height:1.5;margin-top:4px;}
.foot{margin-top:30px;text-align:center;color:var(--muted);font-size:11px;font-family:'JetBrains Mono',monospace;letter-spacing:.05em;line-height:1.7;}
@media (max-width:520px){h1{font-size:27px;}}
"""

MARK_COLOR = {"+": "var(--turf)", "-": "var(--clay)", "~": "var(--steel)"}


def esc(x):
    return html.escape(str(x if x is not None else ""))


def fmt_ml(ml):
    if ml is None:
        return "—"
    return f"+{ml}" if ml > 0 else str(ml)


def value_assessment(g):
    """Compare the factor lean against the market price to surface value candidates.
    Returns (pill_text, pill_bg, pill_fg, note_html). Honest by design: it flags
    where the factors cut against the price as a CANDIDATE to check — it never
    claims confirmed value, since the market already prices these same factors."""
    lean = g.get("lean", "even")
    if lean not in ("away", "home"):
        return ("NO CLEAR LEAN", "rgba(138,154,163,.14)", "#8A9AA3", "")

    team = g[lean].get("team") or lean.title()
    lean_imp = g[lean].get("implied")
    opp = "home" if lean == "away" else "away"
    opp_imp = g[opp].get("implied")
    GREEN = "rgba(70,180,122,.14)"
    GOLD = "rgba(242,181,59,.16)"

    if lean_imp is None or opp_imp is None:  # no market price loaded
        note = ('<div class="vnote">No market price loaded — run with an odds key to '
                'check this lean against the line for value.</div>')
        return (f"LEAN \u25B8 {team.upper()}", GREEN, "#46B47A", note)

    if lean_imp < opp_imp - 0.5:  # factors favor the side the market underrates
        note = (f'<div class="vnote val"><b>Possible value.</b> The market has {esc(team)} '
                f"as the underdog at {lean_imp:.0f}%, but today's factors lean {esc(team)} "
                f"— worth checking against your price.</div>")
        return (f"VALUE LOOK \u25B8 {team.upper()}", GOLD, "#F2B53B", note)

    if lean_imp > opp_imp + 0.5:  # factors agree with the market favorite
        note = (f'<div class="vnote">Factors lean {esc(team)}, who the market already '
                f"favors ({lean_imp:.0f}%) — price and read agree, so not a value spot.</div>")
        return (f"LEAN \u25B8 {team.upper()}", GREEN, "#46B47A", note)

    # near coin-flip market, factors tip one way
    note = (f'<div class="vnote val"><b>Edge on a coin flip.</b> The market sees this as '
            f"about even ({lean_imp:.0f}%); today's factors tip {esc(team)} — a marginal "
            f"edge worth a look.</div>")
    return (f"VALUE LOOK \u25B8 {team.upper()}", GOLD, "#F2B53B", note)


def render_card(g):
    away, home = g["away"], g["home"]
    ia = away.get("implied")
    ih = home.get("implied")
    # Bar split: use implied odds if present, else even.
    if ia and ih:
        aw = ia / (ia + ih) * 100
    else:
        aw = 50
    txt, pbg, pfg, vnote = value_assessment(g)

    weight = g.get("weight", 0)
    if weight > 0:
        on = "".join(
            f'<span class="dot{" on" if n <= weight else ""}"></span>' for n in range(1, 5)
        )
        meter = f'<div class="dots">{on}</div><span class="dlabel">lean strength</span>'
    else:
        meter = ""  # even game — no strength to show

    def side_html(s, cls):
        imp = f'{s["implied"]:.0f}% implied' if s.get("implied") is not None else "no line"
        return f"""<div class="side {cls}">
  <div class="team">{esc(s.get('team'))}</div>
  <div class="rec">{esc(s.get('abbr'))} · {esc(s.get('record'))}</div>
  <div class="pit">{esc(s.get('pitcher_name'))} ({esc(s.get('pitcher_hand') or '?')})</div>
  <div class="oddsrow"><span class="ml">{fmt_ml(s.get('ml'))}</span><span class="imp">{imp}</span></div>
</div>"""

    factors = ""
    for f in g.get("factors", []):
        color = MARK_COLOR.get(f.get("m"), "var(--muted)")
        factors += f"""<div class="f"><span class="fmark" style="color:{color}">{esc(f.get('m'))}</span>
<span><span class="flabel">{esc(f.get('label'))} — </span>{esc(f.get('text'))}</span></div>"""

    read = ""
    if g.get("read"):
        read = f'<div class="read"><b>The read</b>{esc(g["read"])}</div>'

    lines_html = ""
    t = g.get("total")
    if t:
        tr = g.get("total_read") or {}
        lines_html = (
            '<div class="lines"><div class="lines-h">Other lines</div>'
            f'<div class="line-row"><span class="line-name">Total {esc(t.get("line"))}</span>'
            f'<span class="line-odds">O {fmt_ml(t.get("over"))} &nbsp;/&nbsp; U {fmt_ml(t.get("under"))}</span></div>'
            + (f'<div class="line-read">{esc(tr.get("note"))}</div>' if tr.get("note") else "")
            + '</div>'
        )

    w = g.get("weather") or {}
    wx = (f'{w.get("temp_f"):.0f}°F · wind {w.get("wind_mph"):.0f}mph'
          if w.get("temp_f") is not None else "—")

    return f"""<div class="card">
  <div class="head">{side_html(away, "away")}{side_html(home, "home")}</div>
  <div class="bar"><i style="width:{aw:.0f}%;background:var(--amber)"></i><i style="width:{100-aw:.0f}%;background:var(--steel)"></i></div>
  <div class="meta"><span><b>Park</b> {esc(g.get('venue'))}</span><span><b>Wx</b> {wx}</span></div>
  <div class="body">
    <div class="leanrow">
      <span class="pill" style="background:{pbg};color:{pfg}">{txt}</span>
      {meter}
    </div>
    {vnote}
    <details>
      <summary>Why</summary>
      <div class="factors">{factors or '<div class="f"><span class="fmark">~</span><span>No notable factors logged.</span></div>'}</div>
      {read}
      {lines_html}
    </details>
  </div>
</div>"""


def pick_of_the_day(games):
    """The single strongest value look: factors lean the market underdog, ranked
    by how many factors agree. Returns (weight, game, lean, implied) or None."""
    best = None
    for g in games:
        lean = g.get("lean")
        if lean not in ("away", "home"):
            continue
        li = g[lean].get("implied")
        opp = "home" if lean == "away" else "away"
        oi = g[opp].get("implied")
        if li is None or oi is None or li > oi + 0.5:
            continue  # no price, or factors just agree with the favorite
        w = g.get("weight", 0)
        if best is None or w > best[0]:
            best = (w, g, lean, li)
    return best


def render_pick(games):
    best = pick_of_the_day(games)
    if not best:
        return ('<div class="pick none"><div class="lab">Today\'s Top Look</div>'
                '<div class="why">Nothing leaning against the prices right now — every '
                "game's factors line up with its line. That's common before lineups post; "
                'check again a couple hours before first pitch.</div></div>')
    w, g, lean, li = best
    team = g[lean].get("team")
    ml = g[lean].get("ml")
    ml_s = (f"+{ml}" if ml > 0 else str(ml)) if ml is not None else ""
    if w >= 3:
        conv = f"the strongest look on the board — {w} factors stack the same way"
    elif w == 2:
        conv = "a modest look — two factors agree"
    else:
        conv = "a thin look — just one factor, so lean lightly"
    why = (f"The factors lean {esc(team)} even though the market makes them the underdog "
           f"at {li:.0f}%. It's {conv}. Strongest signal of the day — but still a candidate, "
           "not a lock: the price already reflects these factors, so this is the game most "
           "worth your own closer look.")
    return (f'<div class="pick"><div class="lab">Today\'s Top Look</div>'
            f'<div class="team">{esc(team)}<span class="ml">{esc(ml_s)}</span></div>'
            f'<div class="why">{why}</div></div>')


def _cat(rows, kinds):
    """(wins, losses, graded_count, logged_count) for the given pick kinds."""
    logged = [e for e in rows if e.get("kind", "value") in kinds]
    graded = [e for e in logged if e.get("result") in ("W", "L")]
    w = sum(1 for e in graded if e["result"] == "W")
    return w, len(graded) - w, len(graded), len(logged)


def render_scoreboard():
    """Compact results strip from picks_log.json (if the tracker has run)."""
    try:
        with open("picks_log.json") as f:
            rows = json.load(f)
    except (FileNotFoundError, ValueError):
        return ""
    if not rows:
        return ""
    cats = (("Value", ("value",)), ("Lean", ("lean",)), ("O/U", ("total",)))
    parts = ['<span class="sb-lab">Scoreboard</span>']

    # one W-L record per bet type
    for label, kinds in cats:
        w, l, n, _ = _cat(rows, kinds)
        parts.append(f'<span class="sb-stat"><b>{label}</b> {w}-{l}</span>')

    graded = [e for e in rows if e.get("result") in ("W", "L")]
    if graded:
        profit = sum(e["profit"] for e in graded if e.get("profit") is not None)
        parts.append(f'<span class="sb-stat"><b>Units</b> {profit:+.1f}</span>')
        parts.append(f'<span class="sb-stat"><b>ROI</b> {profit / len(graded) * 100:+.0f}%</span>')
    else:
        parts.append('<span class="sb-stat" style="color:var(--muted)">no graded picks yet</span>')

    clv = [e["clv_pp"] for e in rows if e.get("clv_pp") is not None]
    if clv:
        beat = sum(1 for c in clv if c > 0)
        parts.append(f'<span class="sb-stat"><b>CLV</b> {sum(clv) / len(clv):+.1f}pts '
                     f'({beat}/{len(clv)} beat close)</span>')

    # progress toward a readable sample — each bet type counts toward its own ~30
    prog = [f"{label} {_cat(rows, kinds)[3]}/30"
            for label, kinds in cats if _cat(rows, kinds)[3] < 30]
    if prog:
        parts.append('<span class="sb-stat" style="color:var(--muted)">building · '
                     + " · ".join(prog) + "</span>")

    return f'<div class="scoreboard">{"".join(parts)}</div>'


def render(slate):
    date = slate.get("date", "")
    cards = "".join(render_card(g) for g in slate.get("games", []))
    demo = " · SAMPLE DATA" if slate.get("_note") else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MLB Briefing {esc(date)}</title><style>{CSS}</style></head>
<body><div class="wrap">
<div class="eyebrow">Daily Matchup Briefing · {esc(date)}{demo}</div>
<h1>The Lineup Card</h1>
<p class="sub">The day's slate with the context that moves games — pitchers, platoon splits, park, weather — so you can read each matchup at a glance.</p>
<div class="note"><b>How to read this.</b> <b style="color:var(--amber)">VALUE LOOK</b> flags games where today's factors lean toward the side the market rates <i>lower</i> — the classic place to hunt value. But it's a <i>candidate, not a verdict</i>: the market already prices these same factors into the line, so a VALUE LOOK means "worth checking against your price," not "the market is wrong." The strength dots show how many factors agree. Log your results over time to learn whether the flags actually hold up.</div>
{render_scoreboard()}
{render_pick(slate.get("games", []))}
{cards if cards else '<p class="sub">No games in this slate.</p>'}
<div class="foot">+ favorable · ~ neutral · − caution&nbsp;&nbsp;|&nbsp;&nbsp;decision-support only<br>bet what you can afford to lose · 21+ where legal</div>
</div></body></html>"""


def main():
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        files = sorted(glob.glob("slate_*.json"))
        if not files:
            print("No slate_*.json found. Run mlb_briefing.py first.", file=sys.stderr)
            return 1
        path = files[-1]

    with open(path) as f:
        slate = json.load(f)

    out = os.path.splitext(path)[0] + ".html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(render(slate))

    print(f"Wrote {out} — open it in your browser ({len(slate.get('games', []))} game(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
