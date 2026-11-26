"""Sports: next game, last result and standing for any team ESPN covers
(soccer, NBA, NFL, MLB, NHL, college, ...). Uses ESPN's public site API, which
needs no key. Find a team with `rmdash sports search "name"`.

Config (one block per team):

    [[sports]]
    name = "Barcelona"
    sport = "soccer"
    league = "esp.1"
    team_id = 83
"""

from __future__ import annotations

import datetime as dt
from typing import Any
from zoneinfo import ZoneInfo

from rmdash.http import get_json

SITE = "https://site.api.espn.com/apis/site/v2/sports"
NICE = {
    "Spanish LALIGA": "La Liga", "UEFA Champions League": "Champions League",
    "Spanish Copa del Rey": "Copa del Rey", "Spanish Supercopa": "Supercopa",
    "English Premier League": "Premier League",
}
# Soccer clubs play in several competitions; these feeds hold their results.
SOCCER_CUPS = ["uefa.champions", "uefa.europa", "esp.copa_del_rey", "esp.super_cup",
               "eng.fa", "eng.league_cup", "ita.coppa_italia", "ger.dfb_pokal", "fra.coupe_de_france"]


def search(query: str) -> list[dict[str, Any]]:
    d = get_json("https://site.web.api.espn.com/apis/common/v3/search",
                 {"query": query, "type": "team", "limit": 10})
    return [{"name": i.get("displayName"), "sport": i.get("sport"), "league": i.get("league"),
             "team_id": i.get("id")} for i in d.get("items", []) if i.get("league")]


def _when(e: dict[str, Any]) -> dt.datetime:
    return dt.datetime.fromisoformat(e["date"].replace("Z", "+00:00"))


def _sides(comp: dict[str, Any], team: str) -> tuple[dict, dict]:
    us = next(c for c in comp["competitors"] if str(c["team"]["id"]) == team)
    them = next(c for c in comp["competitors"] if str(c["team"]["id"]) != team)
    return us, them


def _score(c: dict[str, Any]) -> str:
    s = c.get("score")
    return str(s.get("displayValue") if isinstance(s, dict) else s)


def _name(c: dict[str, Any]) -> str:
    t = c["team"]
    return t.get("shortDisplayName") or t.get("displayName") or "?"


def team_card(t: dict[str, Any], tz: ZoneInfo) -> dict[str, Any]:
    sport, league, team = t["sport"], t["league"], str(t["team_id"])
    now = dt.datetime.now(dt.timezone.utc)
    card: dict[str, Any] = {"name": t.get("name", ""), "sport": sport}

    # Upcoming: soccer's "all" feed spans every competition the club is in.
    fixtures_league = "all" if sport == "soccer" else league
    sched = get_json(f"{SITE}/{sport}/{fixtures_league}/teams/{team}/schedule", {"fixture": "true"})
    events = [e for e in sched.get("events", []) if _when(e) > now - dt.timedelta(hours=3)
              and not e["competitions"][0].get("status", {}).get("type", {}).get("completed")]
    if events:
        e = min(events, key=_when)
        comp = e["competitions"][0]
        us, them = _sides(comp, team)
        kick = _when(e).astimezone(tz)
        lg = (e.get("league") or {}).get("name") or (e.get("seasonType") or {}).get("name") or ""
        card["next"] = {
            "opponent": _name(them), "home": us.get("homeAway") == "home",
            "competition": NICE.get(lg, lg.replace("Spanish ", "")),
            "day": kick.strftime("%a %b %-d"), "time": kick.strftime("%-I:%M %p"),
            "venue": (comp.get("venue") or {}).get("fullName", ""),
            "days_away": (kick.date() - dt.datetime.now(tz).date()).days,
        }

    # Last result: the team's league feed, plus cup feeds for soccer.
    feeds = [league] + (t.get("cups", SOCCER_CUPS) if sport == "soccer" else [])
    last = None
    for lg in feeds:
        try:
            data = get_json(f"{SITE}/{sport}/{lg}/teams/{team}/schedule", {})
        except Exception:  # noqa: BLE001 - a missing cup feed is normal
            continue
        for e in data.get("events", []):
            comp = e["competitions"][0]
            if comp.get("status", {}).get("type", {}).get("completed") and (last is None or e["date"] > last["date"]):
                last = e
    if last:
        comp = last["competitions"][0]
        us, them = _sides(comp, team)
        res = "W" if us.get("winner") else ("L" if them.get("winner") else "D")
        card["last"] = {"opponent": _name(them), "score": f"{_score(us)}–{_score(them)}",
                        "result": res, "home": us.get("homeAway") == "home"}

    # Standing: walk every group (conferences/divisions) to find the team.
    try:
        table = get_json(f"https://site.api.espn.com/apis/v2/sports/{sport}/{league}/standings", {})
        groups = table.get("children") or [table]
        for g in groups:
            for x in (g.get("standings") or {}).get("entries", []):
                if str(x["team"]["id"]) == team:
                    s = {st["name"]: st.get("displayValue") for st in x["stats"]}
                    card["table"] = {"rank": s.get("rank") or s.get("playoffSeed"),
                                     "points": s.get("points"), "record": s.get("overall")
                                     or (f"{s['wins']}–{s['losses']}" if s.get("wins") else None),
                                     "group": g.get("name") if len(groups) > 1 else None}
    except Exception:  # noqa: BLE001
        pass
    return card


def sports(cfg: dict[str, Any], tz: ZoneInfo) -> list[dict[str, Any]]:
    return [team_card(t, tz) for t in cfg.get("sports", []) if t.get("enabled", True)]
