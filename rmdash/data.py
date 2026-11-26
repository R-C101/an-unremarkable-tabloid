"""Collects everything the dashboard shows into one plain dict.

Every source is optional and fails soft: if the weather API is down or a
calendar URL is wrong, that section shows a short notice instead of breaking
the whole render.
"""

from __future__ import annotations

import datetime as dt
import json
import random
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

USER_AGENT = "rmdash/0.1 (+https://github.com/)"
TIMEOUT = 15

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


def get_json(url: str, params: dict[str, Any]) -> Any:
    full = url + "?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(full, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.load(r)


def geocode(name: str) -> dict[str, Any]:
    res = get_json("https://geocoding-api.open-meteo.com/v1/search",
                   {"name": name, "count": 1, "format": "json"})
    if not res.get("results"):
        raise ValueError(f"Could not find a place called {name!r}")
    r = res["results"][0]
    label = ", ".join(x for x in (r.get("name"), r.get("admin1"), r.get("country_code")) if x)
    return {"name": label, "latitude": r["latitude"], "longitude": r["longitude"],
            "timezone": r.get("timezone", "auto")}


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


def air_quality(cfg: dict[str, Any]) -> dict[str, Any] | None:
    scale = cfg.get("units", {}).get("aqi", "us")
    field = "us_aqi" if scale == "us" else "european_aqi"
    loc = cfg["location"]
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
            "scale": "US AQI" if scale == "us" else "EU AQI"}


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


def collect(cfg: dict[str, Any], base: Path) -> dict[str, Any]:
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
    ctx["now"] = now
    ctx["updated"] = fmt_time(now)

    if cfg.get("air_quality", {}).get("enabled", True):
        try:
            ctx["aqi"] = air_quality(cfg)
        except Exception:  # noqa: BLE001
            ctx["aqi"] = None

    try:
        ctx["calendar"] = calendar(cfg, tz, now.date())
    except Exception as e:  # noqa: BLE001
        ctx["calendar"] = None
        ctx["problems"].append(f"Calendar unavailable ({type(e).__name__})")
    if ctx["calendar"] and ctx["calendar"]["errors"]:
        ctx["problems"].append("A calendar feed could not be read")

    n = cfg.get("notes", {})
    ctx["notes_title"] = n.get("title", "Notes")
    ctx["notes"] = notes(base / n.get("file", "notes.md"))
    q = cfg.get("quotes", {})
    ctx["quote"] = quote(base / q.get("file", "quotes.txt"), now.date()) if q.get("enabled", True) else None
    return ctx
