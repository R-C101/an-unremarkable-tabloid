"""Collects everything the dashboard shows into one plain dict.

Every source is optional and fails soft: if the weather API is down or a
calendar URL is wrong, that section shows a short notice instead of breaking
the whole render.
"""

from __future__ import annotations

import datetime as dt
import random
import urllib.request
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from rmdash.http import TIMEOUT, USER_AGENT, get_json

# WMO weather interpretation codes -> (description, icon)
WMO = {
    0: ("Clear", "sun"),
    1: ("Mostly clear", "sun"),
    2: ("Partly cloudy", "partly"),
    3: ("Overcast", "cloud"),
    45: ("Fog", "fog"),
    48: ("Freezing fog", "fog"),
    51: ("Light drizzle", "drizzle"),
    53: ("Drizzle", "drizzle"),
    55: ("Heavy drizzle", "drizzle"),
    56: ("Freezing drizzle", "drizzle"),
    57: ("Freezing drizzle", "drizzle"),
    61: ("Light rain", "rain"),
    63: ("Rain", "rain"),
    65: ("Heavy rain", "rain"),
    66: ("Freezing rain", "rain"),
    67: ("Freezing rain", "rain"),
    71: ("Light snow", "snow"),
    73: ("Snow", "snow"),
    75: ("Heavy snow", "snow"),
    77: ("Snow grains", "snow"),
    80: ("Light showers", "rain"),
    81: ("Showers", "rain"),
    82: ("Heavy showers", "rain"),
    85: ("Snow showers", "snow"),
    86: ("Heavy snow showers", "snow"),
    95: ("Thunderstorm", "storm"),
    96: ("Thunderstorm, hail", "storm"),
    99: ("Thunderstorm, hail", "storm"),
}

US_AQI = [(50, "Good"), (100, "Moderate"), (150, "Unhealthy for sensitive groups"),
          (200, "Unhealthy"), (300, "Very unhealthy"), (10_000, "Hazardous")]
EU_AQI = [(20, "Good"), (40, "Fair"), (60, "Moderate"), (80, "Poor"),
          (100, "Very poor"), (10_000, "Extremely poor")]


def geocode(name: str) -> dict[str, Any]:
    res = get_json("https://geocoding-api.open-meteo.com/v1/search",
                   {"name": name, "count": 1, "format": "json"})
    if not res.get("results"):
        raise ValueError(f"Could not find a place called {name!r}")
    r = res["results"][0]
    label = ", ".join(x for x in (r.get("name"), r.get("admin1"), r.get("country_code")) if x)
    return {"name": label, "latitude": r["latitude"], "longitude": r["longitude"],
            "timezone": r.get("timezone", "auto"), "country": r.get("country", "")}


def describe(code: int | None, is_day: bool = True) -> tuple[str, str]:
    text, icon = WMO.get(int(code) if code is not None else -1, ("—", "cloud"))
    if not is_day and icon in ("sun", "partly"):
        icon = "moon" if icon == "sun" else "partly-night"
    return text, icon


def weather(cfg: dict[str, Any]) -> dict[str, Any]:
    loc = cfg["location"]
    fahrenheit = cfg.get("units", {}).get("temperature", "fahrenheit") == "fahrenheit"
    wind_unit = cfg.get("units", {}).get("wind", "mph" if fahrenheit else "kmh")
    data = get_json("https://api.open-meteo.com/v1/forecast", {
        "latitude": loc["latitude"], "longitude": loc["longitude"],
        "timezone": loc.get("timezone", "auto"),
        "temperature_unit": "fahrenheit" if fahrenheit else "celsius",
        "wind_speed_unit": wind_unit,
        "precipitation_unit": "inch" if fahrenheit else "mm",
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,"
                   "weather_code,wind_speed_10m,is_day",
        "hourly": "temperature_2m,weather_code,precipitation_probability,is_day",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                 "precipitation_probability_max,sunrise,sunset",
        "forecast_days": 7,
    })
    tz = ZoneInfo(data["timezone"])
    now = dt.datetime.now(tz)
    cur = data["current"]
    text, icon = describe(cur["weather_code"], bool(cur.get("is_day", 1)))

    hourly = []
    h = data["hourly"]
    for i, t in enumerate(h["time"]):
        when = dt.datetime.fromisoformat(t).replace(tzinfo=tz)
        if when < now.replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1):
            continue
        if len(hourly) >= 12:
            break
        if (when.hour % 2) != 0:  # every other hour keeps the strip readable
            continue
        _, hicon = describe(h["weather_code"][i], bool(h["is_day"][i]))
        hourly.append({"label": fmt_hour(when), "temp": round(h["temperature_2m"][i]),
                       "icon": hicon, "rain": h["precipitation_probability"][i]})

    days = []
    d = data["daily"]
    for i, t in enumerate(d["time"]):
        day = dt.date.fromisoformat(t)
        dtext, dicon = describe(d["weather_code"][i])
        days.append({
            "date": day, "name": day.strftime("%a"),
            "high": round(d["temperature_2m_max"][i]), "low": round(d["temperature_2m_min"][i]),
            "text": dtext, "icon": dicon, "rain": d["precipitation_probability_max"][i],
            "sunrise": fmt_time(dt.datetime.fromisoformat(d["sunrise"][i])),
            "sunset": fmt_time(dt.datetime.fromisoformat(d["sunset"][i])),
        })

    return {
        "tz": data["timezone"], "now": now,
        "temp": round(cur["temperature_2m"]), "feels": round(cur["apparent_temperature"]),
        "humidity": cur["relative_humidity_2m"], "wind": round(cur["wind_speed_10m"]),
        "wind_unit": {"kmh": "km/h", "ms": "m/s", "mph": "mph", "kn": "kn"}[wind_unit],
        "text": text, "icon": icon, "unit": "F" if fahrenheit else "C",
        "today": days[0], "days": days[1:6], "hourly": hourly,
    }


def air_quality(cfg: dict[str, Any], env: dict[str, str] | None = None) -> dict[str, Any] | None:
    """Ground-station AQI from WAQI when WAQI_TOKEN is set (free key at
    aqicn.org/data-platform/token), else Open-Meteo's modelled estimate."""
    loc = cfg["location"]
    token = (env or {}).get("WAQI_TOKEN")
    if token:
        try:
            d = get_json(f"https://api.waqi.info/feed/geo:{loc['latitude']};{loc['longitude']}/",
                         {"token": token})
            if d.get("status") == "ok" and isinstance(d["data"].get("aqi"), (int, float)):
                value = round(d["data"]["aqi"])
                label = next(lbl for limit, lbl in US_AQI if value <= limit)
                station = d["data"].get("city", {}).get("name", "").split(",")[0]
                pm25 = d["data"].get("iaqi", {}).get("pm25", {}).get("v")
                return {"value": value, "label": label, "pm25": pm25, "scale": "US AQI",
                        "source": station or "nearest station"}
        except Exception:  # noqa: BLE001 - fall back to the model
            pass
    scale = cfg.get("units", {}).get("aqi", "us")
    field = "us_aqi" if scale == "us" else "european_aqi"
    data = get_json("https://air-quality-api.open-meteo.com/v1/air-quality", {
        "latitude": loc["latitude"], "longitude": loc["longitude"],
        "current": f"{field},pm2_5", "timezone": "auto"})
    value = data["current"].get(field)
    if value is None:
        return None
    value = round(value)
    bands = US_AQI if scale == "us" else EU_AQI
    label = next(lbl for limit, lbl in bands if value <= limit)
    return {"value": value, "label": label, "pm25": data["current"].get("pm2_5"),
            "scale": "US AQI" if scale == "us" else "EU AQI", "source": "model estimate"}


def calendar(cfg: dict[str, Any], tz: ZoneInfo, today: dt.date) -> dict[str, Any] | None:
    cal_cfg = cfg.get("calendar", {})
    urls = [u for u in cal_cfg.get("ics_urls", []) if u]
    if not urls:
        return None
    import icalendar
    import recurring_ical_events

    days_ahead = int(cal_cfg.get("days_ahead", 3))
    start = dt.datetime.combine(today, dt.time.min, tz)
    end = start + dt.timedelta(days=days_ahead + 1)
    events, errors = [], []
    for url in urls:
        try:
            req = urllib.request.Request(url.replace("webcal://", "https://", 1),
                                         headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                cal = icalendar.Calendar.from_ical(r.read())
            for ev in recurring_ical_events.of(cal).between(start, end):
                s = ev.get("DTSTART").dt
                all_day = not isinstance(s, dt.datetime)
                if all_day:
                    sday, when = s, None
                else:
                    s = s.astimezone(tz) if s.tzinfo else s.replace(tzinfo=tz)
                    sday, when = s.date(), s
                e_end = ev.get("DTEND").dt if ev.get("DTEND") else None
                if isinstance(e_end, dt.datetime):
                    e_end = e_end.astimezone(tz) if e_end.tzinfo else e_end.replace(tzinfo=tz)
                    if e_end < dt.datetime.now(tz):
                        continue  # already over
                events.append({"day": sday, "start": when, "all_day": all_day,
                               "title": str(ev.get("SUMMARY", "(no title)")).strip(),
                               "time": "All day" if all_day else fmt_time(when)})
        except Exception as e:  # noqa: BLE001 - one bad feed must not kill the render
            errors.append(f"{type(e).__name__}: {e}"[:120])

    events.sort(key=lambda e: (e["day"], not e["all_day"], e["start"] or start))
    by_day: dict[dt.date, list] = {}
    for e in events:
        by_day.setdefault(e["day"], []).append(e)
    upcoming = []
    for i in range(1, days_ahead + 1):
        day = today + dt.timedelta(days=i)
        upcoming.append({"date": day, "label": day_label(day, today), "events": by_day.get(day, [])})
    return {"today": by_day.get(today, []), "upcoming": upcoming, "errors": errors}


def notes(path: Path) -> list[str]:
    if not path.exists():
        return []
    lines = [ln.strip().lstrip("-*• ").strip() for ln in path.read_text("utf-8").splitlines()]
    return [ln for ln in lines if ln and not ln.startswith("#")]


def quote(path: Path, today: dt.date) -> dict[str, str] | None:
    if not path.exists():
        return None
    entries = []
    for ln in path.read_text("utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        text, _, author = ln.partition("|")
        entries.append({"text": text.strip(), "author": author.strip()})
    if not entries:
        return None
    return random.Random(today.toordinal()).choice(entries)  # same quote all day


def fmt_time(t: dt.datetime) -> str:
    return t.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ")


def fmt_hour(t: dt.datetime) -> str:
    return t.strftime("%I %p").lstrip("0")


def day_label(day: dt.date, today: dt.date) -> str:
    if day == today + dt.timedelta(days=1):
        return "Tomorrow"
    return day.strftime("%A")


def _span(m: int) -> str:
    return f"{m} min" if m < 60 else f"{m // 60} h {m % 60} min" if m % 60 else f"{m // 60} h"


def glance(cfg: dict[str, Any], now: dt.datetime, ctx: dict[str, Any]) -> dict[str, Any]:
    """'Today at a glance': next meeting, task counts, and day/week/year progress."""
    upcoming = [e for e in ((ctx.get("calendar") or {}).get("today") or [])
                if not e["all_day"] and e.get("start") and e["start"] > now]
    nxt = None
    if upcoming:
        e = upcoming[0]
        nxt = {"title": e["title"], "time": e["time"], "in": _span(int((e["start"] - now).total_seconds() // 60))}
    a, b = (int(x[:2]) * 60 + int(x[3:]) for x in cfg["glance"]["workday"].split("-"))
    m = now.hour * 60 + now.minute
    day = min(max((m - a) / (b - a), 0), 1) if b > a else 0
    week = (now.weekday() + m / 1440) / 7
    y0 = dt.datetime(now.year, 1, 1, tzinfo=now.tzinfo)
    year = (now - y0) / (dt.datetime(now.year + 1, 1, 1, tzinfo=now.tzinfo) - y0)
    items = (ctx.get("tasks") or {}).get("items", [])
    return {
        "next": nxt, "meetings_left": len(upcoming),
        "overdue": sum(1 for i in items if i.get("when") == "Overdue"),
        "due_today": sum(1 for i in items if str(i.get("when", "")).startswith("Today")),
        "high": sum(1 for i in items if i.get("high")),
        "bars": [
            {"label": "Workday", "pct": round(day * 100),
             "note": "not started" if m < a else "done" if m >= b else f"{_span(b - m)} left"},
            {"label": f"Week {now.isocalendar().week}", "pct": round(week * 100), "note": now.strftime("%A")},
            {"label": str(now.year), "pct": round(year * 100), "note": f"{(dt.date(now.year, 12, 31) - now.date()).days} days left"},
        ],
    }


def collect(cfg: dict[str, Any], base: Path, battery: dict[str, Any] | None = None,
            at: dt.time | None = None) -> dict[str, Any]:
    """Gather everything for one render. `battery` comes from the tablet; `at`
    pretends it's that time of day (for previewing the timed screens)."""
    from rmdash import screens
    from rmdash.device import load_env
    from rmdash.sources import extras
    from rmdash.sources.sports import sports
    from rmdash.sources.ticktick import tasks

    env = load_env(base)
    ctx: dict[str, Any] = {"cfg": cfg, "problems": []}
    try:
        ctx["weather"] = weather(cfg)
        tz = ZoneInfo(ctx["weather"]["tz"])
    except Exception as e:  # noqa: BLE001
        ctx["weather"] = None
        ctx["problems"].append(f"Weather unavailable ({type(e).__name__})")
        tz_name = cfg["location"].get("timezone", "auto")
        tz = ZoneInfo(tz_name) if tz_name != "auto" else dt.datetime.now().astimezone().tzinfo
    now = dt.datetime.now(tz)
    if at:
        now = now.replace(hour=at.hour, minute=at.minute)
    ctx["now"] = now
    ctx["updated"] = fmt_time(now)
    ctx["battery"] = battery if cfg["battery"].get("show", True) else None
    ctx.update(screens.pick(cfg, now, battery))
    screen = ctx["screen"]

    def soft(key: str, label: str, fn: Any, *args: Any) -> None:
        try:
            ctx[key] = fn(*args)
        except Exception as e:  # noqa: BLE001 - one dead source must not blank the page
            ctx[key] = None
            ctx["problems"].append(f"{label} unavailable ({type(e).__name__})")

    ctx["xkcd"] = ctx["onthisday"] = ctx["headlines"] = None
    if cfg["xkcd"].get("enabled") and screen in ("morning", "night"):
        soft("xkcd", "XKCD", extras.xkcd)
    if cfg["onthisday"].get("enabled") and screen == "night":
        soft("onthisday", "On this day", extras.on_this_day, now.date(), int(cfg["onthisday"]["items"]))
    if cfg["headlines"].get("enabled") and cfg["headlines"].get("feeds") and screen == "morning":
        soft("headlines", "Headlines", extras.headlines, cfg["headlines"]["feeds"], int(cfg["headlines"]["per_feed"]))

    if cfg.get("air_quality", {}).get("enabled", True):
        try:
            ctx["aqi"] = air_quality(cfg, env)
        except Exception:  # noqa: BLE001
            ctx["aqi"] = None

    try:
        ctx["calendar"] = calendar(cfg, tz, now.date())
    except Exception as e:  # noqa: BLE001
        ctx["calendar"] = None
        ctx["problems"].append(f"Calendar unavailable ({type(e).__name__})")
    if ctx["calendar"] and ctx["calendar"]["errors"]:
        ctx["problems"].append("A calendar feed could not be read")

    try:
        ctx["sports"] = sports(cfg, tz)
    except Exception as e:  # noqa: BLE001
        ctx["sports"] = []
        ctx["problems"].append(f"Sports unavailable ({type(e).__name__})")
    try:
        ctx["tasks"] = tasks(cfg, base, env, tz)
    except Exception as e:  # noqa: BLE001
        ctx["tasks"] = None
        ctx["problems"].append(f"TickTick unavailable ({type(e).__name__})")

    # Morning shows what's due today; night shows what's due tomorrow.
    items = (ctx["tasks"] or {}).get("items", [])
    today = now.date()
    ctx["due_today"] = [i for i in items if i["due"] and i["due"].date() <= today]
    ctx["due_tomorrow"] = [i for i in items if i["due"] and i["due"].date() <= today + dt.timedelta(days=1)]

    ctx["glance"] = glance(cfg, now, ctx) if cfg["glance"].get("enabled") and screen == "day" else None

    n = cfg.get("notes", {})
    ctx["notes_title"] = n.get("title", "Notes")
    ctx["notes"] = notes(base / n.get("file", "notes.md"))
    q = cfg.get("quotes", {})
    ctx["quote"] = quote(base / q.get("file", "quotes.txt"), now.date()) if q.get("enabled", True) else None
    return ctx
