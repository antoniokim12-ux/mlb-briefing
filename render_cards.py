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

BUILD = "top5-record"  # bump when shipping; shows in the page footer to verify deploys

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
.sb-note{display:block;width:100%;color:var(--muted);font-size:10px;margin-top:6px;opacity:.75;}
.sb-stat{color:var(--bone);}
.sb-stat b{color:var(--muted);font-weight:500;}
.dayover{border:1px solid var(--line);border-radius:10px;background:var(--panel2);padding:30px 24px;text-align:center;margin:6px 0 0;}
.dayover .lab{font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.2em;text-transform:uppercase;color:var(--amber);}
.dayover .big{font-family:'Archivo Narrow',sans-serif;font-weight:700;font-size:24px;margin:10px 0 6px;}
.dayover .msg{font-size:14px;color:#D4D9DB;line-height:1.6;max-width:500px;margin:0 auto;}
.todays{border:1px solid var(--line);border-radius:10px;background:var(--panel);padding:15px 17px;margin:6px 0 0;}
.todays .lab{font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--amber);margin-bottom:8px;}
.todays .grp{display:flex;flex-wrap:wrap;align-items:center;gap:7px;margin:8px 0;}
.todays .gl{font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);width:42px;flex:none;}
.chip{display:inline-flex;align-items:center;gap:6px;font-size:13px;font-weight:600;padding:4px 9px;border-radius:7px;border:1px solid var(--line);background:var(--panel2);}
.chip.val{border-color:rgba(242,181,59,.5);}
.chip.lean{border-color:rgba(70,180,122,.45);}
.chip.ou{border-color:rgba(111,168,199,.45);}
.chip .px{font-family:'JetBrains Mono',monospace;font-weight:700;color:var(--muted);font-size:12px;}
.chip .gm{color:var(--muted);font-weight:500;font-size:11px;}
.todays .none{color:var(--muted);font-size:12px;}
.todays .dis{color:var(--muted);font-size:11.5px;margin-top:10px;line-height:1.5;}
.trow{display:flex;align-items:center;gap:9px;padding:8px 4px;border-bottom:1px solid var(--line);}
.trow:last-of-type{border-bottom:none;}
.trow.locked{opacity:.55;}
.trow .rk{font-family:'JetBrains Mono',monospace;color:var(--muted);font-size:12px;width:14px;flex:none;}
.trow .ty{font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:.06em;text-transform:uppercase;padding:2px 6px;border-radius:5px;border:1px solid var(--line);flex:none;}
.trow .ty.lean{color:var(--turf);border-color:rgba(70,180,122,.45);}
.trow .ty.ou{color:var(--steel);border-color:rgba(111,168,199,.45);}
.trow .tpick{font-weight:700;font-size:14px;}
.trow .tpx{font-family:'JetBrains Mono',monospace;font-weight:700;color:var(--muted);font-size:12px;}
.trow .dots{color:var(--turf);font-size:11px;letter-spacing:1px;margin-left:auto;}
.trow .dots .off{color:var(--line);}
.trow .tgm{font-family:'JetBrains Mono',monospace;color:var(--muted);font-size:11px;flex:none;}
.chip.locked{opacity:.6;border-style:dashed;}
.chip .lk,.lockbadge{font-family:'JetBrains Mono',monospace;font-size:9.5px;letter-spacing:.12em;color:var(--muted);border:1px solid var(--line);border-radius:4px;padding:1px 4px;}
.lockbadge{color:var(--clay);}
.card.started{opacity:.62;}
.card.started .pill{filter:grayscale(.5);}
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
                'check this lean against the line.</div>')
        return (f"LEAN \u25B8 {team.upper()}", GREEN, "#46B47A", note)

    if lean_imp > opp_imp + 0.5:  # factors agree with the market favorite — a lean
        note = (f'<div class="vnote">Factors lean {esc(team)}, who the market already '
                f"favors ({lean_imp:.0f}%).</div>")
        return (f"LEAN \u25B8 {team.upper()}", GREEN, "#46B47A", note)

    # Factors on the underdog, or a near coin-flip: no lean we act on.
    return ("NO CLEAR LEAN", "rgba(138,154,163,.14)", "#8A9AA3", "")


def render_card(g, started=False, lock=None):
    away, home = g["away"], g["home"]
    ia = away.get("implied")
    ih = home.get("implied")
    # Bar split: use implied odds if present, else even.
    if ia and ih:
        aw = ia / (ia + ih) * 100
    else:
        aw = 50
    txt, pbg, pfg, vnote = value_assessment(g)
    # If this game has a logged pick, the locked version is the source of truth —
    # show it so the card can't disagree with the Today's Picks roundup.
    if lock and lock.get("ml") and lock["ml"].get("kind") == "lean":
        lm = lock["ml"]
        team_u = esc(lm.get("team")).upper()
        txt, pbg, pfg = f"LEAN \u25B8 {team_u}", "rgba(70,180,122,.14)", "#46B47A"
        vnote = (f'<div class="vnote"><b>Locked pick.</b> Frozen at {fmt_ml(lm.get("price"))} '
                 'when it was given — your tracked number, even if the live line has moved.</div>')

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
    lt = (lock or {}).get("total")
    t = g.get("total")
    if lt:  # locked O/U pick — show the frozen read so it matches the roundup
        side = (lt.get("side") or "").upper()
        lines_html = (
            '<div class="lines"><div class="lines-h">Other lines</div>'
            f'<div class="line-row"><span class="line-name">Total {esc(lt.get("line"))}</span>'
            f'<span class="line-odds">{esc(side)} {fmt_ml(lt.get("price"))}</span></div>'
            f'<div class="line-read">Total {esc(lt.get("line"))}: your locked {esc(side)} pick, '
            f'frozen at {fmt_ml(lt.get("price"))} when it was given.</div></div>'
        )
    elif t:
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
    book = (f'<span><b>Book</b> {esc(g.get("odds_book"))}</span>'
            if g.get("odds_book") else "")

    return f"""<div class="card{' started' if started else ''}">
  <div class="head">{side_html(away, "away")}{side_html(home, "home")}</div>
  <div class="bar"><i style="width:{aw:.0f}%;background:var(--amber)"></i><i style="width:{100-aw:.0f}%;background:var(--steel)"></i></div>
  <div class="meta"><span><b>Park</b> {esc(g.get('venue'))}</span><span><b>Wx</b> {wx}</span>{book}</div>
  <div class="body">
    <div class="leanrow">
      <span class="pill" style="background:{pbg};color:{pfg}">{txt}</span>
      {'<span class="lockbadge">● LOCKED</span>' if started else meter}
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


def _norm(s):
    return "".join(c for c in (s or "").lower() if c.isalnum())


def _started_lookup(games):
    """frozenset({norm away, norm home}) -> has the game started?"""
    now = dt.datetime.now(dt.timezone.utc)
    out = {}
    for g in games:
        t = _parse_game_time(g.get("game_time"))
        key = frozenset((_norm(g["away"].get("team")), _norm(g["home"].get("team"))))
        out[key] = bool(t and t <= now)
    return out


def _locked_today(date):
    """Locked picks from the log, indexed BOTH by game id and by team pair, so a card
    can find its frozen pick even if team names don't normalize identically.
    Keys are ('pk', game_pk) and ('pair', frozenset(teams))."""
    try:
        with open("picks_log.json") as f:
            rows = [e for e in json.load(f) if e.get("date") == date]
    except (FileNotFoundError, ValueError):
        return {}
    out = {}
    for e in rows:
        kind = e.get("kind")
        if kind == "total":
            parts = [p.strip() for p in (e.get("opp_team") or "").split("@")]
            pair = frozenset(_norm(p) for p in parts) if len(parts) == 2 else None
            field, val = "total", {"side": e.get("pick_side"), "line": e.get("line"),
                                   "price": e.get("log_ml")}
        elif kind in ("value", "lean"):
            pair = frozenset((_norm(e.get("pick_team")), _norm(e.get("opp_team"))))
            field, val = "ml", {"kind": kind, "team": e.get("pick_team"),
                                "price": e.get("log_ml")}
        else:
            continue
        keys = []
        if e.get("game_pk") is not None:
            keys.append(("pk", e["game_pk"]))
        if pair:
            keys.append(("pair", pair))
        for k in keys:
            out.setdefault(k, {})[field] = val
    return out


def _lock_for(g, locked):
    """Merge any locked ml/total for this game, matching by id first then team pair."""
    merged = {}
    pair = locked.get(("pair", frozenset((_norm(g["away"].get("team")),
                                          _norm(g["home"].get("team"))))))
    if pair:
        merged.update(pair)
    pk = g.get("game_pk")
    if pk is not None and ("pk", pk) in locked:
        merged.update(locked[("pk", pk)])  # id match wins
    return merged or None


def _dots(n, total=4):
    n = max(0, min(total, int(n or 0)))
    return '<span class="dots">' + '●' * n + '<span class="off">' + '○' * (total - n) + '</span></span>'


def top_picks(games, date, n=5):
    """The day's strongest reads, ranked by how many factors agree. Reads the locked
    log so prices/strengths are frozen. Returns a list (possibly empty), or None if
    nothing is logged yet (caller falls back to the live slate)."""
    try:
        with open("picks_log.json") as f:
            rows = [e for e in json.load(f)
                    if e.get("date") == date and e.get("kind") in ("lean", "total")]
    except (FileNotFoundError, ValueError):
        return None
    if not rows:
        return None

    started = _started_lookup(games)
    by_pk = {g.get("game_pk"): g for g in games}
    by_pair = {frozenset((_norm(g["away"].get("team")), _norm(g["home"].get("team")))): g
               for g in games}

    picks = []
    for e in rows:
        kind = e.get("kind")
        if kind == "lean":
            pair = frozenset((_norm(e.get("pick_team")), _norm(e.get("opp_team"))))
        else:
            parts = [p.strip() for p in (e.get("opp_team") or "").split("@")]
            pair = frozenset(_norm(p) for p in parts) if len(parts) == 2 else frozenset()
        g = by_pk.get(e.get("game_pk")) or by_pair.get(pair)
        gm = (f'{g["away"].get("abbr","")}@{g["home"].get("abbr","")}' if g
              else (e.get("opp_team") or "").replace(" @ ", "@"))
        picks.append({
            "kind": kind, "label": esc(e.get("pick_team")), "price": fmt_ml(e.get("log_ml")),
            "score": int(e.get("weight") or 0), "pair": pair,
            "pk": (g.get("game_pk") if g else e.get("game_pk")), "gm": gm,
            "started": started.get(pair, False),
        })
    picks.sort(key=lambda p: (-p["score"], 0 if p["kind"] == "lean" else 1, p["label"]))
    return picks[:n]


def _day_top_keys(entries, n=5):
    """Keys of the picks that were the top-N reads on their own day — the ones the page
    actually surfaced. Uses the same ranking the front page does: strength desc, lean
    before O/U, then label. Every other pick stays in the log but isn't counted in the
    record, so the scoreboard reflects only what the bot chose to show."""
    by_day = {}
    for e in entries:
        if e.get("kind") in ("lean", "total") and e.get("key"):
            by_day.setdefault(e.get("date"), []).append(e)
    keep = set()
    for rows in by_day.values():
        rows.sort(key=lambda e: (-int(e.get("weight") or 0),
                                 0 if e.get("kind") == "lean" else 1,
                                 (e.get("pick_team") or "")))
        keep.update(e["key"] for e in rows[:n])
    return keep


def render_picks_today(top, games):
    """Render the ranked top-5 reads. `top` is from top_picks(); None -> slate fallback."""
    if top is None:
        return _render_picks_from_slate(games)
    if not top:
        return ('<div class="todays"><div class="lab">Today\'s Top Reads</div>'
                '<div class="none">No reads against the prices yet — common before '
                'lineups post. Check back a couple hours before first pitch.</div></div>')
    rows = ""
    for i, p in enumerate(top, 1):
        lock = '<span class="lk">LOCKED</span>' if p["started"] else ""
        ty = "ou" if p["kind"] == "total" else "lean"
        label = "O/U" if p["kind"] == "total" else "Lean"
        rows += (f'<div class="trow{" locked" if p["started"] else ""}">'
                 f'<span class="rk">{i}</span>'
                 f'<span class="ty {ty}">{label}</span>'
                 f'<span class="tpick">{p["label"]}</span>'
                 f'<span class="tpx">{p["price"]}</span>'
                 f'{_dots(p["score"])}'
                 f'<span class="tgm">{p["gm"]}</span>{lock}</div>')
    return (f'<div class="todays"><div class="lab">Today\'s Top {len(top)} Reads</div>{rows}'
            '<div class="dis">The strongest reads of the day, ranked by how many factors '
            'agree (the dots). Frozen at the price each was given; <b>LOCKED</b> = game '
            'started. Strong reads, still candidates — not locks.</div></div>')


def _render_picks_from_slate(games):
    """Fallback used before any picks are logged: derive the roundup from live odds."""
    leans_, totals = [], []
    for g in games:
        txt = value_assessment(g)[0]
        lean = g.get("lean")
        if lean in ("away", "home") and txt.startswith("LEAN"):
            leans_.append((esc(g[lean].get("team") or lean.title()), fmt_ml(g[lean].get("ml")), False))
        tr = g.get("total_read") or {}
        t = g.get("total") or {}
        if tr.get("side") in ("over", "under") and t:
            price = t.get("over") if tr["side"] == "over" else t.get("under")
            gm = f'{g["away"].get("abbr", "")}@{g["home"].get("abbr", "")}'
            totals.append((f'{tr["side"].title()} {esc(t.get("line"))}', fmt_ml(price), gm, False))

    if not (leans_ or totals):
        return ('<div class="todays"><div class="lab">Today\'s Picks</div>'
                '<div class="none">No leans against the prices yet — common before lineups '
                'post. Check back a couple hours before first pitch.</div></div>')

    def chips(items, cls, ou=False):
        if not items:
            return '<span class="none">none</span>'
        if ou:
            return "".join(f'<span class="chip ou">{lbl}<span class="px">{p}</span>'
                           f'<span class="gm">{gm}</span></span>' for lbl, p, gm, _ in items)
        return "".join(f'<span class="chip {cls}">{t}<span class="px">{p}</span></span>'
                       for t, p, _ in items)

    return ('<div class="todays"><div class="lab">Today\'s Picks</div>'
            f'<div class="grp"><span class="gl">Lean</span>{chips(leans_, "lean")}</div>'
            f'<div class="grp"><span class="gl">O/U</span>{chips(totals, "ou", ou=True)}</div>'
            '<div class="dis">Candidates to check against your price — not locks. '
            'The market already prices the same factors in.</div></div>')


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


def _rank_key(e):
    """Ranking used to choose a day's top reads. Must mirror top_picks():
    strongest first, leans before totals on a tie, then label."""
    return (-int(e.get("weight") or 0),
            0 if e.get("kind") == "lean" else 1,
            e.get("pick_team") or "")


def _chosen_keys(rows, n=5):
    """Log keys for the picks the bot actually surfaced — each day's top-n reads.
    The record counts only these, not everything logged behind the scenes.
    Reconstructed per date from the same ranking the page shows, so the record
    always matches the picks on the board."""
    by_date = {}
    for e in rows:
        if e.get("kind") in ("lean", "total"):
            by_date.setdefault(e.get("date"), []).append(e)
    keys = set()
    for es in by_date.values():
        es.sort(key=_rank_key)
        keys.update(e.get("key") for e in es[:n])
    return keys


def _parse_game_time(s):
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def slate_is_over(slate):
    """True once every game in the slate has started — nothing left to bet.
    Uses each game's first-pitch time; if no times are known, treats the day as live."""
    times = [t for g in slate.get("games", [])
             if (t := _parse_game_time(g.get("game_time")))]
    if not times:
        return False
    return max(times) <= dt.datetime.now(dt.timezone.utc)


def _today_record(date):
    """(wins, losses) for picks logged on this date, or None if nothing graded yet."""
    try:
        with open("picks_log.json") as f:
            rows = json.load(f)
    except (FileNotFoundError, ValueError):
        return None
    g = [e for e in rows if e.get("date") == date and e.get("result") in ("W", "L")]
    if not g:
        return None
    top_keys = _day_top_keys([e for e in rows if e.get("kind") in ("lean", "total")])
    g = [e for e in g if e.get("key") in top_keys]
    if not g:
        return None
    w = sum(1 for e in g if e["result"] == "W")
    return w, len(g) - w


def render_dayover(slate):
    """The end-of-day view: a wrap notice instead of the matchup cards."""
    rec = _today_record(slate.get("date", ""))
    today = (f'<div class="big">Today: {rec[0]}-{rec[1]}</div>'
             if rec else '<div class="big">That\'s a wrap</div>')
    return (f'<div class="dayover"><div class="lab">Day\'s done</div>{today}'
            '<div class="msg">All of today\'s games are underway — nothing left to bet. '
            'The scoreboard above keeps updating as games go final. '
            'Check back tomorrow for the next card.</div></div>')


def render_scoreboard():
    """Compact results strip from picks_log.json (if the tracker has run)."""
    try:
        with open("picks_log.json") as f:
            rows = json.load(f)
    except (FileNotFoundError, ValueError):
        return ""
    if not rows:
        return ""
    rows = [e for e in rows if e.get("kind") in ("lean", "total")]  # value retired
    if not rows:
        return ""
    top_keys = _day_top_keys(rows)          # count only the reads the page surfaced
    rows = [e for e in rows if e.get("key") in top_keys]
    if not rows:
        return ""
    cats = (("Lean", ("lean",)), ("O/U", ("total",)))
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

    return f'<div class="scoreboard">{"".join(parts)}<span class="sb-note">record counts the day\'s top 5 reads only</span></div>'


def render(slate):
    date = slate.get("date", "")
    demo = " · SAMPLE DATA" if slate.get("_note") else ""
    head = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MLB Briefing {esc(date)}</title><style>{CSS}</style></head>
<body><div class="wrap">
<div class="eyebrow">Daily Matchup Briefing · {esc(date)}{demo}</div>
<h1>The Lineup Card</h1>"""
    foot = ('<div class="foot">+ favorable · ~ neutral · − caution&nbsp;&nbsp;|&nbsp;&nbsp;'
            'decision-support only<br>bet what you can afford to lose · 21+ where legal'
            f'<br><span style="opacity:.6">build {BUILD}</span></div>'
            '</div></body></html>')

    if slate_is_over(slate):
        # Day's done — show results + a wrap notice, not the slate.
        return f"{head}\n{render_scoreboard()}\n{render_dayover(slate)}\n{foot}"

    games = slate.get("games", [])
    started = _started_lookup(games)
    locked = _locked_today(date)
    top = top_picks(games, date, 5)

    def _pair(g):
        return frozenset((_norm(g["away"].get("team")), _norm(g["home"].get("team"))))

    if top:  # show only the games behind the top reads
        allow_pk = {p["pk"] for p in top}
        allow_pair = {p["pair"] for p in top}
        shown = [g for g in games
                 if g.get("game_pk") in allow_pk or _pair(g) in allow_pair]
    else:    # before anything's logged, show the full slate
        shown = games

    cards = "".join(render_card(g, started.get(_pair(g), False), _lock_for(g, locked))
                    for g in shown)
    return f"""{head}
<p class="sub">The day's strongest reads — the games where the most factors line up — with the context behind each: pitchers, platoon splits, park, weather, bullpens.</p>
<div class="note"><b>How to read this.</b> Each day the bot surfaces only its <b style="color:var(--amber)">top {len(top) if top else 5} reads</b> — the leans and O/U calls where the most factors agree (the dots). These are <i>candidates, not locks</i>: the market already prices these same factors into the line, so a read means "worth checking against your price," not "the market is wrong." Prices are frozen at the moment each read was given. Every read is logged behind the scenes so you can learn, over time, whether the strongest ones actually hold up.</div>
{render_scoreboard()}
{render_picks_today(top, games)}
{cards if cards else '<p class="sub">No reads on the board yet.</p>'}
{foot}"""


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
