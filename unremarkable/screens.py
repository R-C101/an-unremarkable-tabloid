"""Which screen to show, and what the masthead says, for a given time and battery.

  morning      a greeting, today's meetings, what's due, headlines, On this day
  day          the working dashboard: sports, calendar, tasks, XKCD
  night        tomorrow's plan and a comic to end the day
  lowbattery   "I need a charge": weather plus a big plea to be plugged in

During the day screen the masthead says "Good afternoon" / "Good evening" for one
refresh when that part of the day begins, then goes back to the dashboard title.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

PARTS = [(5, "morning"), (12, "afternoon"), (17, "evening"), (21, "night")]


def _minutes(hhmm: str) -> int:
    h, m = hhmm.strip().split(":")
    return int(h) * 60 + int(m)


def in_window(window: str, t: dt.datetime) -> bool:
    """'21:30-05:00' style windows; may wrap past midnight. Empty = never."""
    if not window:
        return False
    a, b = (_minutes(x) for x in window.split("-"))
    m = t.hour * 60 + t.minute
    return a <= m < b if a <= b else (m >= a or m < b)


def part_of_day(t: dt.datetime) -> str:
    part = "night"
    for hour, name in PARTS:
        if t.hour >= hour:
            part = name
    return part


def pick(cfg: dict[str, Any], now: dt.datetime, battery: dict[str, Any] | None) -> dict[str, Any]:
    d, s, b = cfg["dashboard"], cfg["screens"], cfg["battery"]
    name = d.get("name", "").strip()
    hello = lambda part: f"Good {part}, {name}" if name else f"Good {part}"  # noqa: E731

    if battery and b.get("low") and battery["level"] <= int(b["low"]) and not battery["charging"]:
        return {"screen": "lowbattery", "masthead": "I need a charge", "sad": True}
    if in_window(s.get("morning", ""), now):
        return {"screen": "morning", "masthead": hello("morning")}
    if in_window(s.get("night", ""), now):
        return {"screen": "night", "masthead": hello("night")}

    masthead = d["title"]
    if s.get("greet", True):
        every = int(cfg["schedule"]["minutes"])
        for hour, part in PARTS:
            start = now.replace(hour=hour, minute=0, second=0, microsecond=0)
            if part in ("afternoon", "evening") and start <= now < start + dt.timedelta(minutes=every):
                masthead = hello(part)
    return {"screen": "day", "masthead": masthead}
