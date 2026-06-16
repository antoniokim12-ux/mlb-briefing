#!/usr/bin/env python3
"""
MLB Briefing — results logger + CLV tracker
===========================================

Records the tool's value looks, grades them against final scores, captures the
closing line for Closing Line Value, and reports whether the picks actually hold
up. This is the honest scoreboard for the whole tool — run it for a few weeks
before trusting any pick with money.

WHY CLV MATTERS
---------------
Closing Line Value = did the price you logged beat where the line closed?
Consistently beating the close predicts long-term profit better than your
win/loss record does, and it tells you far sooner. CLV here is de-vigged
(the bookmaker margin removed) so it's a fair comparison.

DAILY USE
---------
  python track_results.py log slate_2026-06-14.json     # record today's value looks
  # ...a couple hours later, re-fetch the slate, then:
  python track_results.py close slate_2026-06-14.json    # capture closing lines -> CLV
  python track_results.py grade                          # grade finished games from scores
  python track_results.py report                         # show the scoreboard

Notes:
  * 'log' needs a slate built WITH odds (no price = no pick to track).
  * 'log' is safe to re-run; the first price seen for a game is kept as "your price".
  * Picks are flat-staked at 1 unit for ROI.
"""

import argparse
import datetime as dt
import json
import os
import sys

import requests

MLB_API = "https://statsapi.mlb.com/api/v1"
TIMEOUT = 20
LOG_PATH = "picks_log.json"


# ───────────────────────── math helpers ─────────────────────────

def implied_pct(ml):
    """American odds -> implied win probability in percent."""
    if ml is None:
        return None
    a = float(ml)
    p = (-a / (-a + 100)) if a < 0 else (100 / (a + 100))
    return p * 100


def fair_pct(team_pct, opp_pct):
    """De-vig: a team's fair probability with the bookmaker margin removed."""
    if team_pct is None or opp_pct is None or (team_pct + opp_pct) == 0:
        return None
    return team_pct / (team_pct + opp_pct) * 100


def profit_on_win(ml):
    """Units won per 1 unit staked if the bet hits (American odds)."""
    a = float(ml)
    return a / 100 if a > 0 else 100 / abs(a)


# ───────────────────────── log store ─────────────────────────

def load_log():
    if not os.path.exists(LOG_PATH):
        return {}
    try:
        with open(LOG_PATH) as f:
            return {e["key"]: e for e in json.load(f)}
    except (ValueError, KeyError):
        return {}


def save_log(entries):
    with open(LOG_PATH, "w") as f:
        json.dump(list(entries.values()), f, indent=2)


# ───────────────────────── pick detection ─────────────────────────

def leans(games):
    """Every game whose factors lean a side, tagged by kind.
      'value' = lean is on the side the market rates lower (a VALUE LOOK)
      'lean'  = lean agrees with the market favorite (little edge)
    Returns list of (game, lean_side, pick_implied, opp_implied, kind)."""
    out = []
    for g in games:
        lean = g.get("lean")
        if lean not in ("away", "home"):
            continue
        opp = "home" if lean == "away" else "away"
        li = g[lean].get("implied")
        oi = g[opp].get("implied")
        if li is None or oi is None:
            continue
        kind = "value" if li <= oi + 0.5 else "lean"
        out.append((g, lean, li, oi, kind))
    return out


# ───────────────────────── modes ─────────────────────────

def mode_log(slate_path):
    slate = _read_json(slate_path)
    date = slate.get("date", "")
    rows = leans(slate.get("games", []))
    if not rows:
        print(f"No leans in {slate_path} (need odds loaded, and lineups posted "
              "for leans to appear). Nothing logged.")
        return 0

    # The day's top look is the strongest VALUE look, matching the card banner.
    value_rows = [r for r in rows if r[4] == "value"]
    top = max(value_rows, key=lambda x: x[0].get("weight", 0))[0] if value_rows else None

    entries = load_log()
    added = 0
    for g, lean, li, oi, kind in rows:
        key = f'{date}:{g.get("game_pk")}'
        if key in entries:
            continue  # keep the first price we saw as "your price"
        opp = "home" if lean == "away" else "away"
        entries[key] = {
            "key": key, "date": date, "game_pk": g.get("game_pk"),
            "pick_team": g[lean].get("team"), "pick_side": lean,
            "opp_team": g[opp].get("team"),
            "log_ml": g[lean].get("ml"),
            "log_implied": round(li, 1),
            "log_fair": round(fair_pct(li, oi), 1),
            "weight": g.get("weight", 0),
            "kind": kind,
            "is_top": g is top,
            "close_ml": None, "close_fair": None, "clv_pp": None,
            "result": None, "pick_score": None, "opp_score": None, "profit": None,
        }
        added += 1

    save_log(entries)
    top_name = top[top["lean"]].get("team") if top else "none"
    print(f"Logged {added} new lean(s) for {date} "
          f"({sum(1 for r in rows if r[4] == 'value')} value, "
          f"{sum(1 for r in rows if r[4] == 'lean')} favorite; top look: {top_name}).")
    return 0


def _parse_iso(s):
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def mode_close(slate_path):
    """Capture the latest pre-game price for today's logged picks and compute CLV.
    Safe to run repeatedly: it refreshes the closing price only for games that
    haven't started, so the last run before first pitch holds the true close."""
    slate = _read_json(slate_path)
    date = slate.get("date", "")
    by_pk = {g.get("game_pk"): g for g in slate.get("games", [])}
    now = dt.datetime.now(dt.timezone.utc)

    entries = load_log()
    updated = 0
    for e in entries.values():
        if e["date"] != date:
            continue
        g = by_pk.get(e["game_pk"])
        if not g:
            continue
        gt = _parse_iso(g.get("game_time"))
        if gt is not None and gt <= now:
            continue  # game underway/finished -> keep the last pre-game capture
        side = e["pick_side"]
        opp = "home" if side == "away" else "away"
        cf = fair_pct(implied_pct(g[side].get("ml")), implied_pct(g[opp].get("ml")))
        if cf is None:
            continue
        e["close_ml"] = g[side].get("ml")
        e["close_fair"] = round(cf, 1)
        e["clv_pp"] = round(cf - e["log_fair"], 1)  # + = you beat the close
        updated += 1

    save_log(entries)
    print(f"Refreshed closing lines for {updated} upcoming pick(s) on {date}.")
    return 0


def fetch_final_scores(date):
    """{game_pk: {'state':..., 'away':score, 'home':score}} for a date."""
    r = requests.get(f"{MLB_API}/schedule", timeout=TIMEOUT,
                     params={"sportId": 1, "date": date})
    r.raise_for_status()
    out = {}
    for d in r.json().get("dates", []):
        for g in d.get("games", []):
            teams = g.get("teams", {})
            out[g.get("gamePk")] = {
                "state": (g.get("status") or {}).get("abstractGameState"),
                "away": (teams.get("away") or {}).get("score"),
                "home": (teams.get("home") or {}).get("score"),
            }
    return out


def grade_entry(e, score):
    """Apply a final score dict to a log entry. Returns True if newly graded."""
    if e["result"] is not None or not score or score.get("state") != "Final":
        return False
    a, h = score.get("away"), score.get("home")
    if a is None or h is None:
        return False
    pick_won = (a > h) if e["pick_side"] == "away" else (h > a)
    e["result"] = "W" if pick_won else "L"
    e["pick_score"] = a if e["pick_side"] == "away" else h
    e["opp_score"] = h if e["pick_side"] == "away" else a
    e["profit"] = round(profit_on_win(e["log_ml"]), 3) if pick_won else -1.0
    return True


def mode_grade():
    entries = load_log()
    ungraded = [e for e in entries.values() if e["result"] is None]
    if not ungraded:
        print("Nothing to grade — all logged picks already have results.")
        return 0

    graded = 0
    for date in sorted({e["date"] for e in ungraded}):
        try:
            scores = fetch_final_scores(date)
        except requests.RequestException as ex:
            print(f"Could not fetch scores for {date}: {ex}", file=sys.stderr)
            continue
        for e in ungraded:
            if e["date"] == date and grade_entry(e, scores.get(e["game_pk"])):
                graded += 1

    save_log(entries)
    print(f"Graded {graded} pick(s). "
          f'{sum(1 for e in entries.values() if e["result"] is None)} still pending '
          "(games not final yet).")
    return 0


def _stat_block(rows, label):
    graded = [e for e in rows if e["result"] in ("W", "L")]
    w = sum(1 for e in graded if e["result"] == "W")
    n = len(graded)
    profit = sum(e["profit"] for e in graded if e["profit"] is not None)
    clv = [e["clv_pp"] for e in rows if e["clv_pp"] is not None]

    print(f"\n{label}")
    print("-" * len(label))
    if n:
        roi = profit / n * 100
        print(f"  Record     {w}-{n - w}  ({w / n * 100:.0f}% win)")
        print(f"  Units      {profit:+.2f} over {n} bets")
        print(f"  ROI        {roi:+.1f}%  (flat 1u stakes)")
    else:
        print("  Record     no graded picks yet")
    if clv:
        beat = sum(1 for c in clv if c > 0)
        print(f"  CLV        {sum(clv) / len(clv):+.1f} pts avg  "
              f"({beat}/{len(clv)} beat the close)")
    else:
        print("  CLV        no closing lines captured yet")


def mode_report():
    entries = list(load_log().values())
    if not entries:
        print("No picks logged yet. Run 'log' on a slate built with odds first.")
        return 0
    print(f"\n===== MLB Briefing — results scoreboard ({len(entries)} picks logged) =====")
    _stat_block(entries, "All picks")
    _stat_block([e for e in entries if e.get("kind", "value") == "value"], "Value looks")
    _stat_block([e for e in entries if e.get("kind") == "lean"], "Favorite leans")
    _stat_block([e for e in entries if e.get("is_top")], "Top Look only")
    print("\nReminder: CLV is the early signal. A positive average CLV over ~30+ picks "
          "is the first real sign the tool is finding something. Win/loss is noisier. "
          "Watch whether VALUE LOOKS beat FAVORITE LEANS — if they don't, the value flag "
          "isn't adding anything.\n")
    return 0


# ───────────────────────── plumbing ─────────────────────────

def _read_json(path):
    with open(path) as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser(description="Log, grade, and report on the tool's picks.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_log = sub.add_parser("log", help="record today's value looks from a slate JSON")
    p_log.add_argument("slate")
    p_close = sub.add_parser("close", help="capture closing lines for CLV from a fresh slate")
    p_close.add_argument("slate")
    sub.add_parser("grade", help="grade finished games from final scores")
    sub.add_parser("report", help="print the results scoreboard")
    args = ap.parse_args()

    try:
        if args.cmd == "log":
            return mode_log(args.slate)
        if args.cmd == "close":
            return mode_close(args.slate)
        if args.cmd == "grade":
            return mode_grade()
        if args.cmd == "report":
            return mode_report()
    except FileNotFoundError as e:
        print(f"File not found: {e.filename}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
