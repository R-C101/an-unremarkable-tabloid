"""Sample data for `rmdash preview --demo`.

Renders a full dashboard (calendar, tasks, a sports fixture) without any of your
own accounts, so screenshots for the README or a bug report never leak personal data.
Weather and air quality are still fetched live for the demo city.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from rmdash import config, data

DEMO_CONFIG = {
    "dashboard": {"title": "The Morning Edition"},
    "location": {"name": "Brooklyn, NY", "latitude": 40.6782, "longitude": -73.9442,
                 "timezone": "America/New_York"},
    "units": {"temperature": "fahrenheit", "aqi": "us"},
    "ticktick": {"enabled": True, "max_items": 6},
    "calendar": {"days_ahead": 3},
}


def _ev(title: str, time: str | None = None) -> dict[str, Any]:
    return {"title": title, "time": time or "All day", "all_day": time is None}


def _task(title: str, when: str = "", high: bool = False) -> dict[str, Any]:
    return {"title": title, "when": when, "high": high}


def collect(base: Path) -> dict[str, Any]:
    cfg = config.merge(config.DEFAULTS, DEMO_CONFIG)
    cfg["calendar"]["ics_urls"] = []  # live calendars stay off in demo mode
    ctx = data.collect(cfg, base)
    today = ctx["now"].date()
    day = lambda n: today + dt.timedelta(days=n)  # noqa: E731
    ctx["calendar"] = {
        "today": [_ev("Team standup", "10 AM"), _ev("Dentist", "4:30 PM")],
        "upcoming": [
            {"date": day(1), "label": "Tomorrow", "events": [_ev("Mia's birthday")]},
            {"date": day(2), "label": day(2).strftime("%A"), "events": [_ev("Farmers market", "9 AM")]},
            {"date": day(3), "label": day(3).strftime("%A"), "events": []},
        ],
        "errors": [],
    }
    groups = [
        {"name": "Home", "items": [
            _task("Renew car insurance", "Overdue", True), _task("Book flights for the holidays", "Today"),
            _task("Fix the squeaky hinge"), _task("Return library books", "Sat"),
            _task("Order more coffee beans"), _task("Call grandma"), _task("Water the ferns")]},
        {"name": "Work", "items": [
            _task("Ship the onboarding redesign", "Today 3 PM", True), _task("Review Sam's pull request", "Today"),
            _task("Draft Q1 roadmap", "Fri"), _task("Update the status page copy"),
            _task("Prep slides for all-hands", "Mon")]},
    ]
    ctx["tasks"] = {"groups": groups, "items": [i for g in groups for i in g["items"]],
                    "count": sum(len(g["items"]) for g in groups)}
    ctx["sports"] = [{
        "name": "Knicks", "sport": "basketball",
        "next": {"opponent": "Celtics", "home": True, "competition": "NBA", "day": f"{day(2):%a %b} {day(2).day}",
                 "time": "7:30 PM", "venue": "", "days_away": 2},
        "last": {"opponent": "Heat", "score": "112–104", "result": "W", "home": False},
        "table": {"rank": "2", "points": None, "record": "14–6", "group": None},
    }]
    ctx["notes"] = []
    return ctx
