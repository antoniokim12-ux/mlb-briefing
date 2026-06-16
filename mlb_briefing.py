#!/usr/bin/env python3
"""
MLB Daily Matchup Briefing — data fetcher
=========================================

Builds the JSON your card UI consumes. Pulls the day's slate from the free,
official MLB Stats API, adds pitcher platoon splits, lineup handedness (when
lineups are posted), ballpark weather (Open-Meteo, free, no key), and moneyline
odds (The Odds API, free tier), then writes one JSON file for the day.

HONESTY NOTE
------------
The "lean" this produces is a *transparent heuristic* — a tally of the same
public factors the sportsbook already prices in. It is decision-support, not a
claim to beat the line. Log results over time before trusting it.

USAGE
-----
  # Live (run on your own machine, not in a restricted sandbox):
  export ODDS_API_KEY=your_key_here          # optional; odds skipped if unset
  export ANTHROPIC_API_KEY=your_key_here     # optional; AI "read" skipped if unset
  python mlb_briefing.py                      # today
  python mlb_briefing.py --date 2026-06-14
  python mlb_briefing.py --no-splits          # faster; skips per-pitcher split calls

  # Offline self-test (no network) — proves the assembly + scoring logic:
  python mlb_briefing.py --demo

OUTPUT
------
  slate_YYYY-MM-DD.json   # the file your UI reads

DEPENDENCIES
------------
  pip install requests
  # optional, for richer Statcast splits instead of MLB Stats API splits:
  # pip install pybaseball
"""

import argparse
import datetime as dt
import json
import os
import sys

import requests

MLB_API = "https://statsapi.mlb.com/api/v1"
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
ODDS_API = "https://api.the-odds-api.com/v4/sports/baseball_mlb/odds"
ANTHROPIC_API = "https://api.anthropic.com/v1/messages"
TIMEOUT = 20
SEASON = dt.date.today().year

# A pitcher whose OPS-against vs the opponent's dominant batting hand is below
# this is treated as a favorable matchup factor. ~.700 is roughly league-average
# OPS; below it = the pitcher is suppressing that side. Tune to taste.
OPS_AGAINST_GOOD = 0.700
# Share of one-handed batters in a lineup above which we call the lineup "skewed".
HAND_SKEW = 0.60
# Wind at/above this (mph) is flagged as a weather note.
WIND_NOTE_MPH = 15.0


# ───────────────────────── MLB Stats API ─────────────────────────

def get_schedule(date_str):
    """Day's games with probable pitchers, venue coordinates, and team records."""
    params = {
        "sportId": 1,
        "date": date_str,
        "hydrate": "probablePitcher,venue(location),team",
    }
    r = requests.get(f"{MLB_API}/schedule", params=params, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    games = []
    for d in data.get("dates", []):
        for g in d.get("games", []):
            games.append(_parse_game(g))
    return games


def _parse_game(g):
    teams = g.get("teams", {})

    def side(key):
        t = teams.get(key, {})
        team = t.get("team", {})
        rec = t.get("leagueRecord", {})
        pp = t.get("probablePitcher", {})
        return {
            "team": team.get("teamName") or team.get("name", ""),
            "team_full": team.get("name", ""),
            "abbr": team.get("abbreviation", ""),
            "team_id": team.get("id"),
            "record": f'{rec.get("wins", "?")}-{rec.get("losses", "?")}',
            "pitcher_id": pp.get("id"),
            "pitcher_name": pp.get("fullName", "TBD"),
            "pitcher_hand": (pp.get("pitchHand") or {}).get("code"),  # 'L'/'R'
            "ml": None,            # filled from odds
            "implied": None,       # filled from odds
        }

    venue = g.get("venue", {})
    coords = (venue.get("location") or {}).get("defaultCoordinates") or {}
    return {
        "game_pk": g.get("gamePk"),
        "game_time": g.get("gameDate"),     # ISO UTC
        "venue": venue.get("name", ""),
        "lat": coords.get("latitude"),
        "lon": coords.get("longitude"),
        "away": side("away"),
        "home": side("home"),
        "weather": None,
        "factors": [],
        "lean": "even",
        "weight": 1,
        "read": None,
        "total": None,        # {line, over, under} from odds
        "total_read": None,   # preliminary over/under lean
    }


def get_pitcher_splits(pitcher_id, season=SEASON):
    """OPS-against for a pitcher vs RHB ('vr') and LHB ('vl'). Returns {'R':ops,'L':ops}."""
    if not pitcher_id:
        return {}
    params = {
        "stats": "statSplits",
        "group": "pitching",
        "season": season,
        "sitCodes": "vr,vl",
    }
    try:
        r = requests.get(f"{MLB_API}/people/{pitcher_id}/stats",
                         params=params, timeout=TIMEOUT)
        r.raise_for_status()
        out = {}
        for blk in r.json().get("stats", []):
            for split in blk.get("splits", []):
                code = (split.get("split") or {}).get("code")
                ops = (split.get("stat") or {}).get("ops")
                if code == "vr" and ops is not None:
                    out["R"] = float(ops)
                elif code == "vl" and ops is not None:
                    out["L"] = float(ops)
        return out
    except (requests.RequestException, ValueError):
        return {}


def get_lineup_handedness(game_pk):
    """Count L/R batters per side from the posted boxscore lineup.

    Returns {'away': {...}, 'home': {...}} where each holds counts and the
    dominant hand, or marks the lineup as not yet posted.
    """
    result = {"away": _empty_hand(), "home": _empty_hand()}
    try:
        r = requests.get(f"{MLB_API}/game/{game_pk}/boxscore", timeout=TIMEOUT)
        r.raise_for_status()
        box = r.json().get("teams", {})

        # The boxscore gives the batting order but NOT each batter's handedness,
        # so collect the lineup IDs and fetch bat sides in one batched call.
        orders = {s: (box.get(s, {}).get("battingOrder") or []) for s in ("away", "home")}
        hands_by_id = _fetch_bat_sides([pid for ids in orders.values() for pid in ids])

        for side in ("away", "home"):
            counts = {"L": 0, "R": 0, "S": 0}
            for pid in orders[side]:
                hand = hands_by_id.get(pid)
                if hand in counts:
                    counts[hand] += 1
            total = sum(counts.values())
            if total >= 6:  # lineup is posted
                result[side] = _summarize_hand(counts, total)
        return result
    except (requests.RequestException, ValueError):
        return result


def _fetch_bat_sides(player_ids):
    """Map player_id -> bat side code ('L'/'R'/'S') via one /people call."""
    if not player_ids:
        return {}
    try:
        ids = ",".join(str(p) for p in player_ids)
        r = requests.get(f"{MLB_API}/people", params={"personIds": ids}, timeout=TIMEOUT)
        r.raise_for_status()
        out = {}
        for p in r.json().get("people", []):
            code = (p.get("batSide") or {}).get("code")
            if code:
                out[p.get("id")] = code
        return out
    except (requests.RequestException, ValueError):
        return {}


def _empty_hand():
    return {"posted": False, "L": 0, "R": 0, "S": 0, "dominant": None, "share": 0.0}


def _summarize_hand(counts, total):
    # Switch hitters bat opposite the pitcher, so they don't favor either
    # starter's platoon. Count only fixed L/R for the skew signal.
    fixed = counts["L"] + counts["R"]
    dominant, share = None, 0.0
    if fixed:
        if counts["R"] >= counts["L"]:
            dominant, share = "R", counts["R"] / fixed
        else:
            dominant, share = "L", counts["L"] / fixed
    return {"posted": True, **counts, "dominant": dominant, "share": round(share, 2)}


# ───────────────────────── Weather ─────────────────────────

def get_weather(lat, lon, game_time_iso):
    """Temp + wind at the venue for the game hour, from Open-Meteo (free, no key)."""
    if lat is None or lon is None:
        return None
    try:
        r = requests.get(OPEN_METEO, timeout=TIMEOUT, params={
            "latitude": lat, "longitude": lon,
            "hourly": "temperature_2m,wind_speed_10m,wind_direction_10m",
            "wind_speed_unit": "mph", "temperature_unit": "fahrenheit",
            "forecast_days": 2,
        })
        r.raise_for_status()
        h = r.json().get("hourly", {})
        times = h.get("time", [])
        if not times:
            return None
        target = game_time_iso[:13] if game_time_iso else None  # 'YYYY-MM-DDTHH'
        idx = next((i for i, t in enumerate(times) if t[:13] == target), 0)
        return {
            "temp_f": h["temperature_2m"][idx],
            "wind_mph": h["wind_speed_10m"][idx],
            "wind_dir_deg": h["wind_direction_10m"][idx],
            # NOTE: classifying wind as blowing IN vs OUT needs each park's
            # center-field compass bearing (a static per-park dataset). Left as
            # a documented refinement rather than shipped with guessed bearings.
        }
    except (requests.RequestException, ValueError, KeyError, IndexError):
        return None


# ───────────────────────── Odds ─────────────────────────

def implied_prob(american):
    if american is None:
        return None
    a = float(american)
    return (-a / (-a + 100)) if a < 0 else (100 / (a + 100))


def get_odds(api_key):
    """Pull moneyline + full-game totals (first book listed per event).
    Returns {'ml': {team_norm: price}, 'totals': {matchup_key: {line, over, under}}}."""
    empty = {"ml": {}, "totals": {}}
    if not api_key:
        return empty
    try:
        r = requests.get(ODDS_API, timeout=TIMEOUT, params={
            "apiKey": api_key, "regions": "us", "markets": "h2h,totals",
            "oddsFormat": "american",
        })
        r.raise_for_status()
        ml, totals = {}, {}
        for ev in r.json():
            mkey = _matchup_key(ev.get("home_team", ""), ev.get("away_team", ""))
            book = (ev.get("bookmakers") or [{}])[0]
            for mkt in book.get("markets", []):
                k = mkt.get("key")
                if k == "h2h":
                    for oc in mkt.get("outcomes", []):
                        ml[_norm(oc.get("name", ""))] = oc.get("price")
                elif k == "totals":
                    line = over = under = None
                    for oc in mkt.get("outcomes", []):
                        if oc.get("name") == "Over":
                            over, line = oc.get("price"), oc.get("point")
                        elif oc.get("name") == "Under":
                            under, line = oc.get("price"), oc.get("point")
                    if line is not None:
                        totals[mkey] = {"line": line, "over": over, "under": under}
        return {"ml": ml, "totals": totals}
    except (requests.RequestException, ValueError):
        return empty


def _matchup_key(home, away):
    return tuple(sorted([_norm(home), _norm(away)]))


def _norm(name):
    return "".join(ch for ch in name.lower() if ch.isalnum())


def attach_odds(game, odds):
    ml = odds.get("ml", {})
    for side in ("away", "home"):
        s = game[side]
        m = ml.get(_norm(s["team_full"])) or ml.get(_norm(s["team"]))
        if m is not None:
            s["ml"] = m
            p = implied_prob(m)
            s["implied"] = round(p * 100, 1) if p is not None else None
    totals = odds.get("totals", {})
    key = _matchup_key(game["home"]["team_full"], game["away"]["team_full"])
    game["total"] = totals.get(key) or totals.get(
        _matchup_key(game["home"]["team"], game["away"]["team"]))


# ───────────────────────── Factor scoring (transparent heuristic) ─────────────────────────

def build_factors(game, splits_by_pid, hands):
    """Roll the public factors into a lean. Honest + explainable, not an edge claim."""
    factors = []
    score = {"away": 0, "home": 0}

    pairs = [("away", "home"), ("home", "away")]
    for pside, oside in pairs:
        pitcher = game[pside]
        opp_hand = hands.get(oside, _empty_hand())
        sp = splits_by_pid.get(pitcher.get("pitcher_id"), {})

        if opp_hand["posted"] and opp_hand["dominant"] and opp_hand["share"] >= HAND_SKEW:
            dom = opp_hand["dominant"]
            ops_vs = sp.get(dom)
            opp_name = game[oside]["team"]
            if ops_vs is not None:
                if ops_vs <= OPS_AGAINST_GOOD:
                    factors.append({
                        "m": "+", "side": pside, "label": "Handedness matchup",
                        "text": f'{pitcher["pitcher_name"]} holds {dom}HB to a {ops_vs:.3f} OPS; '
                                f'{opp_name} project {int(opp_hand["share"]*100)}% {dom}-handed today.',
                    })
                    score[pside] += 1
                elif ops_vs >= OPS_AGAINST_GOOD + 0.080:
                    factors.append({
                        "m": "-", "side": pside, "label": "Handedness matchup",
                        "text": f'{pitcher["pitcher_name"]} is vulnerable to {dom}HB '
                                f'({ops_vs:.3f} OPS) and {opp_name} skew {dom}-handed.',
                    })
                    score[pside] -= 1
        elif not opp_hand["posted"]:
            factors.append({
                "m": "~", "side": "none", "label": "Lineups",
                "text": f'{game[oside]["team"]} lineup not posted yet — handedness '
                        f'matchup firms up ~2-4 hrs before first pitch.',
            })

    # Weather note (reported, not directionally scored without park bearings).
    w = game.get("weather")
    if w and w.get("wind_mph") is not None and w["wind_mph"] >= WIND_NOTE_MPH:
        factors.append({
            "m": "~", "side": "none", "label": "Wind",
            "text": f'{w["wind_mph"]:.0f} mph wind (dir {w.get("wind_dir_deg","?")}°) — '
                    f'enough to move fly balls; in/out effect depends on park orientation.',
        })

    diff = score["away"] - score["home"]
    if diff > 0:
        game["lean"] = "away"
    elif diff < 0:
        game["lean"] = "home"
    else:
        game["lean"] = "even"
    game["weight"] = min(4, abs(diff))  # 0 = even, 1-4 = lean strength (net factors)
    game["factors"] = factors
    return game


def assess_total(game, splits_by_pid, hands):
    """Preliminary over/under lean. Honest first pass: based on how well the two
    starters suppress the opposing lineups, plus a weather mention. A fuller read
    wants park run-factors, both starters' ERA, and wind DIRECTION (not in yet)."""
    t = game.get("total")
    if not t:
        return
    supps = []
    for pside, oside in (("away", "home"), ("home", "away")):
        sp = splits_by_pid.get(game[pside].get("pitcher_id"), {})
        if not sp:
            continue
        dom = (hands.get(oside) or {}).get("dominant")
        ops = sp.get(dom) if dom else None
        if ops is None:  # fall back to the pitcher's overall split average
            vals = [v for v in sp.values() if v is not None]
            ops = sum(vals) / len(vals) if vals else None
        if ops is not None:
            supps.append(ops)

    side = None
    if len(supps) == 2:
        avg = sum(supps) / 2
        if avg <= 0.690:
            side, why = "under", f"both starters project to suppress these lineups (avg {avg:.3f} OPS-against)"
        elif avg >= 0.770:
            side, why = "over", f"both starters look hittable (avg {avg:.3f} OPS-against)"
        else:
            why = f"starters roughly average (avg {avg:.3f} OPS-against)"
    else:
        why = "not enough split data yet"

    w = game.get("weather") or {}
    wnote = ""
    if w.get("wind_mph") is not None and w["wind_mph"] >= WIND_NOTE_MPH:
        wnote = f" Strong wind ({w['wind_mph']:.0f} mph) could swing it (direction effect pending)."

    body = f"leans {side.upper()} — {why}." if side else f"no clear lean — {why}."
    game["total_read"] = {
        "side": side,
        "line": t.get("line"),
        "note": f"Total {t.get('line')}: {body}{wnote} "
                "(Preliminary — park, ERA, and wind direction still to come.)",
    }


# ───────────────────────── Optional AI "read" ─────────────────────────

def generate_read(game, api_key):
    """Plain-English matchup summary from the assembled factors (optional)."""
    if not api_key or not game["factors"]:
        return None
    bullets = "\n".join(f'- [{f["m"]}] {f["label"]}: {f["text"]}' for f in game["factors"])
    prompt = (
        f'{game["away"]["team"]} ({game["away"]["ml"]}) at {game["home"]["team"]} '
        f'({game["home"]["ml"]}), {game["venue"]}.\nFactors:\n{bullets}\n\n'
        "Write 2-3 sentences for a casual bettor explaining why this game leans the way "
        "it does. Be honest that the book already prices these factors in. No hype, no "
        "guarantees, no betting advice imperatives."
    )
    try:
        r = requests.post(ANTHROPIC_API, timeout=TIMEOUT,
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": "claude-sonnet-4-6", "max_tokens": 220,
                  "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json().get("content", [])).strip()
    except (requests.RequestException, ValueError):
        return None


# ───────────────────────── Orchestration ─────────────────────────

def build_slate(date_str, do_splits=True, do_odds=True, do_read=True):
    odds_key = os.environ.get("ODDS_API_KEY") if do_odds else None
    ai_key = os.environ.get("ANTHROPIC_API_KEY") if do_read else None

    games = get_schedule(date_str)
    odds_map = get_odds(odds_key)

    for g in games:
        attach_odds(g, odds_map)
        g["weather"] = get_weather(g["lat"], g["lon"], g["game_time"])
        hands = get_lineup_handedness(g["game_pk"])

        splits_by_pid = {}
        if do_splits:
            for side in ("away", "home"):
                pid = g[side].get("pitcher_id")
                if pid:
                    splits_by_pid[pid] = get_pitcher_splits(pid)

        build_factors(g, splits_by_pid, hands)
        assess_total(g, splits_by_pid, hands)
        g["read"] = generate_read(g, ai_key)

    return {"date": date_str, "generated": dt.datetime.now().isoformat(timespec="seconds"),
            "games": games}


# ───────────────────────── Offline self-test ─────────────────────────

def demo_slate():
    """Runs the assembly + scoring logic on fixtures — no network. Verifies the
    pipeline end to end so you can see the exact JSON shape your UI consumes."""
    g = _parse_game({
        "gamePk": 999001, "gameDate": "2026-06-14T23:10:00Z",
        "venue": {"name": "Fenway Park",
                  "location": {"defaultCoordinates": {"latitude": 42.346, "longitude": -71.097}}},
        "teams": {
            "away": {"team": {"name": "New York Yankees", "teamName": "Yankees",
                              "abbreviation": "NYY", "id": 147},
                     "leagueRecord": {"wins": 41, "losses": 28},
                     "probablePitcher": {"id": 543037, "fullName": "Gerrit Cole",
                                         "pitchHand": {"code": "R"}}},
            "home": {"team": {"name": "Boston Red Sox", "teamName": "Red Sox",
                              "abbreviation": "BOS", "id": 111},
                     "leagueRecord": {"wins": 37, "losses": 32},
                     "probablePitcher": {"id": 657277, "fullName": "Tanner Houck",
                                         "pitchHand": {"code": "R"}}},
        },
    })
    attach_odds(g, {"ml": {"newyorkyankees": 105, "bostonredsox": -125},
                    "totals": {_matchup_key("Boston Red Sox", "New York Yankees"):
                               {"line": 8.5, "over": -110, "under": -105}}})
    g["weather"] = {"temp_f": 63, "wind_mph": 17, "wind_dir_deg": 40}
    hands = {
        "away": _summarize_hand({"L": 3, "R": 6, "S": 0}, 9),   # NYY lineup
        "home": _summarize_hand({"L": 2, "R": 7, "S": 0}, 9),   # BOS lineup, R-skewed
    }
    splits = {543037: {"R": 0.612, "L": 0.701},   # Cole strong vs RHB
              657277: {"R": 0.745, "L": 0.690}}    # Houck ok
    build_factors(g, splits, hands)
    assess_total(g, splits, hands)
    g["read"] = ("Cole's strong right-on-right numbers line up against a righty-heavy Boston "
                 "lineup, and a stiff wind trims Fenway's usual offense — which is why the "
                 "Yankees read as live at +105. The book already knows all of this; the lean "
                 "is context, not an edge.")
    return {"date": "2026-06-14", "generated": dt.datetime.now().isoformat(timespec="seconds"),
            "games": [g], "_note": "DEMO fixtures — no live data."}


# ───────────────────────── CLI ─────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Build the MLB daily briefing JSON.")
    ap.add_argument("--date", default=dt.date.today().isoformat(), help="YYYY-MM-DD")
    ap.add_argument("--no-splits", action="store_true", help="skip per-pitcher split calls")
    ap.add_argument("--no-odds", action="store_true", help="skip odds (no API key)")
    ap.add_argument("--no-read", action="store_true", help="skip AI read generation")
    ap.add_argument("--demo", action="store_true", help="offline self-test, no network")
    ap.add_argument("--out", default=None, help="output path (default slate_DATE.json)")
    args = ap.parse_args()

    if args.demo:
        slate = demo_slate()
        date_str = slate["date"]
    else:
        date_str = args.date
        try:
            slate = build_slate(date_str, do_splits=not args.no_splits,
                                do_odds=not args.no_odds, do_read=not args.no_read)
        except requests.RequestException as e:
            print(f"Network error talking to a data source: {e}", file=sys.stderr)
            return 1

    out = args.out or f"slate_{date_str}.json"
    with open(out, "w") as f:
        json.dump(slate, f, indent=2)

    n = len(slate["games"])
    leaning = sum(1 for g in slate["games"] if g["lean"] != "even")
    print(f"Wrote {out}: {n} game(s), {leaning} with a context lean, "
          f'{n - leaning} no clear lean.')
    return 0


if __name__ == "__main__":
    sys.exit(main())
