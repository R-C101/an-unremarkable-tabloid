"""Loads config.toml and fills in defaults."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    "dashboard": {"title": "The Morning Edition", "name": "", "orientation": "landscape", "rotate": 90},
    "screens": {"morning": "05:00-09:30", "night": "21:30-05:00", "greet": True},
    "battery": {"show": True, "low": 10},
    "glance": {"enabled": True, "workday": "09:30-19:00"},
    "xkcd": {"enabled": True},
    "onthisday": {"enabled": True, "items": 3},
    "headlines": {"enabled": True, "per_feed": 4, "feeds": [
        {"name": "Hacker News", "url": "https://hnrss.org/frontpage?points=50"},
        {"name": "World", "url": "https://feeds.bbci.co.uk/news/world/rss.xml"},
    ]},
    "location": {"name": "", "latitude": None, "longitude": None, "timezone": "auto"},
    "units": {"temperature": "fahrenheit", "aqi": "us"},
    "air_quality": {"enabled": True},
    "calendar": {"ics_urls": [], "days_ahead": 3},
    "ticktick": {"enabled": False, "lists": [], "only_due": False, "days_ahead": 2, "max_items": 7},
    "sports": [],
    "notes": {"file": "notes.md", "title": "Notes"},
    "quotes": {"enabled": True, "file": "quotes.txt"},
    "schedule": {"minutes": 30},
    "tablet": {"host": "10.11.99.1", "user": "root", "remote_dir": "/home/root/rmdash"},
}


def merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        out[k] = merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def load(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"No config at {path}. Run: rmdash init --city \"Your City\"")
    cfg = merge(DEFAULTS, tomllib.loads(path.read_text("utf-8")))
    if cfg["location"]["latitude"] is None:
        raise SystemExit("Set [location] latitude/longitude in config.toml (or run rmdash init --city ...)")
    return cfg
