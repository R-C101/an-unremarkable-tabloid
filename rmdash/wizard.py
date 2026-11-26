"""`rmdash setup`: an interactive, re-runnable setup wizard.

It asks one question at a time, shows an example for each, and writes config.toml
(settings) and .env (secrets). Run it again any time: your current answers are the
defaults, and a menu lets you change just one part.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import shutil
import sys
import tomllib
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from rmdash import config, device
from rmdash.http import USER_AGENT

HOLIDAYS = {  # Google's public holiday calendars (verified Nov 2026)
    "india": "indian", "usa": "usa", "us": "usa", "united states": "usa", "uk": "uk", "united kingdom": "uk",
    "canada": "canadian", "australia": "australian", "germany": "german", "france": "french",
    "japan": "japanese", "spain": "spain", "italy": "italian", "brazil": "brazilian", "mexico": "mexican",
    "netherlands": "dutch", "ireland": "irish", "singapore": "singapore", "new zealand": "new_zealand",
    "south africa": "sa", "philippines": "philippines",
}
# Countries with an English Google News edition; elsewhere we search for news about the country.
EN_EDITIONS = {"US", "GB", "IN", "AU", "CA", "NZ", "IE", "SG", "ZA", "PH", "NG", "KE", "PK", "MY", "BW", "GH",
               "NA", "TZ", "UG", "ZW", "ET", "LB", "IL", "BD"}
HOLIDAY_URL = "https://calendar.google.com/calendar/ical/en.{}%23holiday%40group.v.calendar.google.com/public/basic.ics"

ORDER = ["dashboard", "location", "units", "screens", "glance", "calendar", "ticktick", "headlines", "xkcd",
         "onthisday", "air_quality", "battery", "notes", "quotes", "schedule", "tablet"]
COMMENTS = {
    "dashboard": "name: for \"Good morning, <name>\". rotate: 90 or 270 (flip if upside down)",
    "screens": "\"HH:MM-HH:MM\" windows (may wrap past midnight); \"\" turns a screen off",
    "glance": "the day screen's \"Today at a glance\" panel; workday drives its progress bar",
    "calendar": "PRIVATE: anyone with these links can read the calendar",
    "ticktick": "lists = [] shows all lists",
    "headlines": "RSS/Atom feeds on the morning screen",
    "battery": "at or below `low` (and not charging) the tablet shows \"I need a charge\"",
    "tablet": "sleep: deep-sleep between refreshes (days of battery instead of hours)",
}

# ── tiny terminal UI ─────────────────────────────────────────────────────────
if os.name == "nt":
    os.system("")  # turns on colour codes in the Windows console
COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if COLOR else s


def bold(s: str) -> str:
    return _c("1", s)


def dim(s: str) -> str:
    return _c("2", s)


def good(s: str) -> str:
    return _c("32", s)


def warn(s: str) -> str:
    return _c("33", s)


def heading(s: str) -> None:
    print("\n" + bold(f"── {s} " + "─" * max(0, 60 - len(s))))


def say(s: str = "") -> None:
    print(s)


def ask(q: str, default: str = "", example: str = "") -> str:
    hint = f" [{default}]" if default else (dim(f" (e.g. {example})") if example else "")
    v = input(f"{q}{hint}: ").strip()
    return v or default


def yes(q: str, default: bool = True) -> bool:
    while True:
        v = input(f"{q} {'[Y/n]' if default else '[y/N]'}: ").strip().lower()
        if not v:
            return default
        if v in ("y", "yes", "n", "no"):
            return v.startswith("y")
        say("Please answer y or n.")


def pick(q: str, options: list[str], default: int | str | None = None, many: bool = False) -> list[int]:
    """Numbered choice. Returns 0-based indexes. With many=True, '1,3' (Enter = the default, or none)."""
    for i, o in enumerate(options, 1):
        say(f"  {i}. {o}")
    d = "" if default is None else default if isinstance(default, str) else str(default + 1)
    while True:
        v = ask(q, d)
        if not v and many:
            return []
        try:
            idx = [int(x) - 1 for x in re.split(r"[,\s]+", v) if x]
            if idx and all(0 <= i < len(options) for i in idx) and (many or len(idx) == 1):
                return idx
        except ValueError:
            pass
        say(f"Type {'numbers like 1,3' if many else 'a number'} from the list.")


def secret(q: str, have: bool) -> str:
    """Typed input is hidden. Enter keeps the saved value."""
    v = getpass.getpass(f"{q}{' [Enter keeps the saved one]' if have else ''} (typing is hidden): ").strip()
    return v


def hhmm(v: str) -> str | None:
    m = re.fullmatch(r"(\d{1,2})(?::?(\d{2}))?\s*(am|pm)?", v.strip().lower())
    if not m:
        return None
    h, mi, ap = int(m[1]), int(m[2] or 0), m[3]
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    return f"{h:02d}:{mi:02d}" if h < 24 and mi < 60 else None


def ask_time(q: str, default: str, example: str) -> str:
    """Returns 'HH:MM' or '' (off)."""
    while True:
        v = ask(q + dim(" ('off' to turn off)"), default, example)
        if v.lower() in ("off", "none", "no"):
            return ""
        t = hhmm(v)
        if t:
            return t
        say("Type a time like 9:30, 21:30 or 9pm.")


# ── config.toml writing ──────────────────────────────────────────────────────
def _val(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{k} = {_val(x)}" for k, x in v.items() if x is not None) + " }"
    if isinstance(v, list):
        if any(isinstance(x, dict) for x in v):
            return "[\n" + "".join(f"  {_val(x)},\n" for x in v) + "]"
        return "[" + ", ".join(_val(x) for x in v) + "]"
    raise TypeError(type(v))


def dumps(cfg: dict[str, Any]) -> str:
    out = ["# Written by `rmdash setup`. Run it again to change things, or edit this file by hand:",
           "# every option is explained in config.example.toml. This file is private (git-ignored).", ""]
    keys = [k for k in ORDER if k in cfg] + [k for k in cfg if k not in ORDER]
    for k in keys:
        v = cfg[k]
        if isinstance(v, list) and all(isinstance(x, dict) for x in v):  # [[sports]]
            if k == "sports":
                out.append("# Teams: find more with `rmdash sports search \"name\"`")
            for item in v:
                out.append(f"[[{k}]]")
                out += [f"{kk} = {_val(vv)}" for kk, vv in item.items() if vv is not None]
                out.append("")
            continue
        if not isinstance(v, dict):
            out.insert(3, f"{k} = {_val(v)}")
            continue
        if k in COMMENTS:
            out.append(f"# {COMMENTS[k]}")
        out.append(f"[{k}]")
        out += [f"{kk} = {_val(vv)}" for kk, vv in v.items() if vv is not None]
        out.append("")
    text = "\n".join(out)
    tomllib.loads(text)  # never write a file we can't read back
    return text


class Setup:
    def __init__(self, base: Path):
        self.base = base
        self.path = base / "config.toml"
        self.cfg: dict[str, Any] = tomllib.loads(self.path.read_text("utf-8")) if self.path.exists() else {}
        self.todo: list[str] = []  # things to do later, printed at the end

    def get(self, section: str, key: str, fallback: Any = None) -> Any:
        if key in self.cfg.get(section, {}):
            return self.cfg[section][key]
        d = config.DEFAULTS.get(section, {})
        return d.get(key, fallback) if isinstance(d, dict) else fallback

    def set(self, section: str, **values: Any) -> None:
        self.cfg.setdefault(section, {}).update(values)

    def env(self) -> dict[str, str]:
        return device.load_env(self.base)

    def set_env(self, **values: str) -> None:
        from rmdash.sources.ticktick import set_env
        set_env(self.base, values)

    def save(self) -> None:
        if self.path.exists():
            shutil.copy(self.path, self.path.with_suffix(".toml.bak"))
        self.path.write_text(dumps(self.cfg), "utf-8")
        say(good("✓ Saved config.toml") + dim("  (the previous version is in config.toml.bak)"))

    # ── sections ─────────────────────────────────────────────────────────────
    def basics(self) -> None:
        heading("You and your dashboard")
        name = ask("Your first name, for \"Good morning, ___\"", self.get("dashboard", "name", ""), "Alex")
        default_title = self.cfg.get("dashboard", {}).get("title", "")
        title = ask("A title for the top of the dashboard", default_title,
                    f"The {name or 'Smith'} Times, Daily Planet, The Morning Edition") or "The Morning Edition"
        self.set("dashboard", name=name, title=title)

        from rmdash.data import geocode
        loc = self.cfg.get("location", {})
        while True:
            city = ask("Your city, for weather and air quality", loc.get("name", ""), "Lisbon, or Springfield, US")
            if loc.get("latitude") is not None and city == loc.get("name"):
                break
            try:
                place = geocode(city)
            except Exception as e:  # noqa: BLE001
                say(warn(f"Couldn't find that ({e}). Try adding the country, e.g. \"Springfield, US\"."))
                continue
            if yes(f"Found {bold(place['name'])}. Is that right?"):
                self.cfg["location"] = place
                loc = place
                break
        us = loc.get("name", "").endswith(", US")
        cur = self.cfg.get("units", {}).get("temperature", "fahrenheit" if us else "celsius")
        f = pick("Temperature in", ["Celsius (°C)", "Fahrenheit (°F)"], 1 if cur == "fahrenheit" else 0)[0]
        self.set("units", temperature=["celsius", "fahrenheit"][f], aqi=self.get("units", "aqi", "us"))
        rot = int(self.get("dashboard", "rotate", 90))
        self.set("dashboard", orientation=self.get("dashboard", "orientation", "landscape"), rotate=rot)
        say(dim("The dashboard is landscape. If it shows up upside down on the tablet, run setup again and pick\n"
                "\"Look and screens\" to flip it."))

    def screens(self) -> None:
        heading("Look and screens")
        say("The dashboard changes through the day:\n"
            "  • Morning: \"Good morning\", today's meetings, headlines and an XKCD comic\n"
            "  • Day: your calendar, tasks, sports and a \"Today at a glance\" panel\n"
            "  • Night: tomorrow's plan, tomorrow's weather, On this day and an XKCD")
        morning = self.get("screens", "morning", "05:00-09:30")
        night = self.get("screens", "night", "21:30-05:00")
        m_end = ask_time("Show the morning screen until", morning.split("-")[1] if morning else "09:30", "9:30")
        n_start = ask_time("Show the night screen from", night.split("-")[0] if night else "21:30", "9:30pm")
        greet = yes("Say \"Good afternoon\" / \"Good evening\" at the top for a while at 12:00 and 17:00?",
                    self.get("screens", "greet", True))
        self.set("screens", morning=f"05:00-{m_end}" if m_end else "",
                 night=f"{n_start}-05:00" if n_start else "", greet=greet)
        work = self.get("glance", "workday", "09:30-19:00")
        ws = ask_time("Your workday starts at", work.split("-")[0], "9:30") or "09:30"
        we = ask_time("and ends at", work.split("-")[1], "19:00") or "19:00"
        self.set("glance", enabled=True, workday=f"{ws}-{we}")
        if yes("Flip the dashboard upside down? (only if it shows up upside down on the tablet)", False):
            self.set("dashboard", rotate=270 if int(self.get("dashboard", "rotate", 90)) == 90 else 90)

    def calendar(self) -> None:
        heading("Calendar")
        urls: list[str] = list(self.get("calendar", "ics_urls", []))
        holiday = [u for u in urls if "%23holiday%40" in u]
        private = [u for u in urls if u not in holiday]
        if private:
            say(f"You have {len(private)} private calendar link(s) set up.")
            if not yes("Keep them?"):
                private = []
        say("Your calendar is read through its private iCal link (read-only). How to find it:\n"
            f"  • {bold('Google')}: calendar.google.com → ⚙ Settings → click your calendar on the left →\n"
            "    \"Integrate calendar\" → copy \"Secret address in iCal format\"\n"
            f"  • {bold('iCloud')}: Calendar app → right-click the calendar → Share → Public Calendar → copy the link\n"
            f"  • {bold('Outlook')}: outlook.com → ⚙ Settings → Calendar → Shared calendars → Publish → copy the ICS link\n"
            + dim("  Treat the link like a password: anyone who has it can read that calendar."))
        while True:
            u = ask("Paste a calendar link (Enter when done)").strip()
            if not u:
                break
            u = re.sub(r"^webcal://", "https://", u)
            ok, info = _check_ics(u)
            if ok or yes(warn(f"That link didn't work ({info}). Keep it anyway?"), False):
                private.append(u)
                say(good(f"✓ Added ({info})") if ok else "Added.")
        if not private:
            self.todo.append("Add your calendar: run `rmdash setup` again and choose Calendar "
                             "(it shows where to find the link for Google, iCloud and Outlook).")
        names = sorted({k for k, v in HOLIDAYS.items() if any(f"en.{v}%23" in u for u in holiday)}, key=len)
        country = ask("Public holidays for which country? (Enter to skip, '-' for none)",
                      names[-1].title() if names else "", "India, USA, UK, Germany")
        holiday = []
        if country and country != "-":
            slug = HOLIDAYS.get(country.lower())
            if slug:
                holiday = [HOLIDAY_URL.format(slug)]
            else:
                say(warn("I don't have that country's holiday calendar. Known: ")
                    + ", ".join(sorted({k.title() for k in HOLIDAYS if len(k) > 3})))
        self.set("calendar", ics_urls=private + holiday, days_ahead=self.get("calendar", "days_ahead", 3))

    def tasks(self) -> None:
        heading("To-do lists (TickTick)")
        say(dim("Other apps (Todoist, Things, Google Tasks) aren't supported yet. Notes in notes.md are shown either way."))
        if not yes("Do you use TickTick and want your tasks on the dashboard?", bool(self.get("ticktick", "enabled"))):
            self.set("ticktick", enabled=False)
            return
        env = self.env()
        if not (env.get("TICKTICK_CLIENT_ID") and env.get("TICKTICK_CLIENT_SECRET")) or \
                yes("Re-enter your TickTick app's Client ID and Secret?", False):
            say("TickTick needs a free \"developer app\" so rmdash can read (never change) your tasks:\n"
                "  1. Go to https://developer.ticktick.com and sign in → Manage Apps → + App Name (call it rmdash)\n"
                "  2. Edit the app. Set OAuth redirect URL to:  http://127.0.0.1:8765/callback  and save\n"
                "  3. Copy its Client ID and Client Secret here")
            cid = ask("Client ID")
            csec = secret("Client Secret", False)
            if not cid or not csec:
                say(warn("Skipped. Run setup again when you have them."))
                self.todo.append("Connect TickTick: run `rmdash setup` again and choose To-do lists.")
                return
            self.set_env(TICKTICK_CLIENT_ID=cid, TICKTICK_CLIENT_SECRET=csec)
            env = self.env()
        from rmdash.sources import ticktick
        if not env.get("TICKTICK_TOKEN") or yes("Log in to TickTick again?", False):
            say("A browser window opens: approve read-only access, then come back here.")
            try:
                ticktick.login(self.base, env)
            except (SystemExit, Exception) as e:  # noqa: BLE001
                say(warn(f"TickTick login didn't finish: {e}"))
                self.todo.append("Connect TickTick: run `rmdash ticktick login`.")
                self.set("ticktick", enabled=True)
                return
            env = self.env()
        try:
            names = ["Inbox"] + [p["name"] for p in ticktick.projects(self.base, env)]
        except Exception as e:  # noqa: BLE001
            say(warn(f"Couldn't read your lists ({e}). Showing all of them."))
            names = []
        lists: list[str] = list(self.get("ticktick", "lists", []))
        if names:
            say("Which lists should appear? Each gets its own column (2-3 fit nicely).")
            cur = ",".join(str(names.index(x) + 1) for x in lists if x in names)
            idx = pick("Numbers, separated by commas" + ("" if cur else " (Enter for all)"), names, cur or None,
                       many=True)
            lists = [names[i] for i in idx]
        self.set("ticktick", enabled=True, lists=lists, only_due=self.get("ticktick", "only_due", False),
                 days_ahead=self.get("ticktick", "days_ahead", 2), max_items=self.get("ticktick", "max_items", 7))

    def sports(self) -> None:
        heading("Sports")
        say("Follow any team ESPN covers: football/soccer, NBA, NFL, MLB, NHL, college sports.\n"
            "It shows the next game, the last result and the league position.")
        teams = [t for t in self.cfg.get("sports", []) if yes(f"Keep following {bold(t.get('name', '?'))}?")]
        from rmdash.sources.sports import search
        while True:
            q = ask("Team to follow (Enter when done)", example="Arsenal, Lakers, Real Madrid" if not teams else "")
            if not q:
                break
            try:
                rows = search(q)
            except Exception as e:  # noqa: BLE001
                say(warn(f"Search failed ({e}). Try again?"))
                continue
            if not rows:
                say("Nothing found. Try the team's common name, e.g. \"Man United\".")
                continue
            opts = [f"{r['name']}  {dim(r['league'])}" for r in rows] + ["None of these"]
            i = pick("Which one", opts, 0)[0]
            if i < len(rows):
                team = {k: rows[i][k] for k in ("name", "sport", "league", "team_id")}
                team["team_id"] = int(team["team_id"]) if str(team["team_id"]).isdigit() else team["team_id"]
                teams.append(team)
                say(good(f"✓ Following {rows[i]['name']}"))
        self.cfg["sports"] = teams

    def headlines(self) -> None:
        heading("Morning headlines")
        feeds: list[dict[str, str]] = list(self.get("headlines", "feeds", []))
        if feeds and "headlines" in self.cfg:
            say("Current feeds: " + ", ".join(f.get("name", "?") for f in feeds))
            if not yes("Keep them?"):
                feeds = []
        else:
            feeds = []
        if not yes("Show headlines on the morning screen?", self.get("headlines", "enabled", True)):
            self.set("headlines", enabled=False)
            return
        loc = self.cfg.get("location", {})
        cc = (loc.get("name", "").rsplit(", ", 1) + [""])[1][:2].upper() or "US"
        if cc in EN_EDITIONS:
            local = f"https://news.google.com/rss?hl=en-{cc}&gl={cc}&ceid={cc}:en"
        else:
            country = loc.get("country") or cc
            local = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
                {"q": f"{country} when:1d", "hl": "en-US", "gl": "US", "ceid": "US:en"})
        presets = [
            ("Tech", "Hacker News front page", "https://hnrss.org/frontpage?points=50"),
            ("World", "BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
            (f"{cc} news", f"Top stories in your country ({cc}) from Google News, in English", local),
        ]
        have = {f["url"] for f in feeds}
        avail = [p for p in presets if p[2] not in have]
        extra = ["A topic you choose (e.g. \"climate tech\", \"Formula 1\")", "Any RSS/Atom feed link"]
        while True:
            opts = [p[1] for p in avail] + extra
            idx = pick("Add which? Numbers separated by commas (Enter when done)", opts, many=True)
            if not idx:
                break
            for i in idx:
                if i < len(avail):
                    feeds.append({"name": avail[i][0], "url": avail[i][2]})
                elif i == len(avail):
                    topic = ask("Topic", example="sports analytics")
                    if topic:
                        q = urllib.parse.quote_plus(f"{topic} when:7d")
                        feeds.append({"name": topic.title()[:18], "url": f"https://news.google.com/rss/search?q={q}"})
                else:
                    url = ask("Feed link", example="https://www.theverge.com/rss/index.xml")
                    if url:
                        feeds.append({"name": ask("Short name for it", example="The Verge")[:18] or "News", "url": url})
            avail = [p for p in avail if p[2] not in {f["url"] for f in feeds}]
        if len(feeds) > 3:
            say(warn("Tip: 2-3 feeds fit best; the layout trims the rest."))
        self.set("headlines", enabled=bool(feeds), per_feed=self.get("headlines", "per_feed", 4),
                 feeds=feeds or config.DEFAULTS["headlines"]["feeds"])

    def extras(self) -> None:
        heading("Extras")
        self.set("xkcd", enabled=yes("XKCD comic on the morning and night screens?", self.get("xkcd", "enabled", True)))
        self.set("onthisday", enabled=yes("Wikipedia's \"On this day\" on the night screen?",
                                          self.get("onthisday", "enabled", True)))
        self.set("quotes", enabled=yes("A quote of the day (from quotes.txt) when there's room?",
                                       self.get("quotes", "enabled", True)))
        notes = self.base / "notes.md"
        if not notes.exists() and (self.base / "notes.example.md").exists():
            shutil.copy(self.base / "notes.example.md", notes)
        say(dim(f"Notes: anything you write in {notes.name} (one item per line) shows on the day screen."))
        self.set("air_quality", enabled=yes("Show air quality?", self.get("air_quality", "enabled", True)))
        if self.cfg["air_quality"]["enabled"]:
            have = bool(self.env().get("WAQI_TOKEN"))
            say(dim("Optional: a free token from https://aqicn.org/data-platform/token/ uses your nearest real "
                    "monitoring station\n(more accurate in many cities). Without it, a forecast model is used."))
            tok = ask("WAQI token (Enter to skip)", "saved" if have else "")
            if tok and tok != "saved":
                self.set_env(WAQI_TOKEN=tok)

    def tablet(self) -> None:
        from rmdash import cli
        heading("Connect the tablet")
        env = self.env()
        say("rmdash talks to the tablet over SSH, the reMarkable's built-in remote login.\n"
            f"On the tablet, open {bold('Settings → Help → Copyrights and licenses')} and scroll to the bottom.\n"
            "You'll see the SSH password and the tablet's IP addresses.")
        cur = env.get("RM_HOST") or self.get("tablet", "host", "10.11.99.1")
        how = pick("How is the tablet connected?",
                   ["Wi-Fi (same network as this computer; best for a wall)", "USB cable (address 10.11.99.1)"],
                   1 if cur == "10.11.99.1" else 0)[0]
        host = "10.11.99.1" if how == 1 else ask("The tablet's Wi-Fi IP address (the one that isn't 10.11.99.1)",
                                                 cur if cur != "10.11.99.1" else "", "192.168.1.50")
        values = {"RM_HOST": host, "RM_USER": env.get("RM_USER", "root")}
        pw = secret("SSH password from that screen", bool(env.get("RM_PASSWORD")))
        if pw:
            values["RM_PASSWORD"] = pw
        self.set_env(**values)
        say(good("✓ Saved to .env") + dim(" (private, never committed)"))
        self.set("tablet", sleep=yes("Let the tablet sleep between refreshes? (lasts days instead of hours; "
                                     "it can take up to 30 min to answer commands)", self.get("tablet", "sleep", True)))
        self.save()
        say("\nPairing installs a key so the password isn't needed again, backs up your notebooks to the\n"
            "backup folder, and copies a small display program into /home/root/rmdash. Nothing else changes;\n"
            "restarting the tablet always brings back the normal reMarkable app.")
        if not yes("Pair the tablet now?"):
            self.todo.append("Pair the tablet: `rmdash tablet setup`, then `rmdash push`.")
            return
        ns = argparse.Namespace(dir=self.base, action="setup")
        try:
            cli.cmd_tablet(ns)
        except SystemExit as e:
            say(warn(f"Pairing failed: {e}\nCheck the IP and password, that the tablet is awake and on the same "
                     "Wi-Fi, then run setup again."))
            self.todo.append("Pair the tablet: run `rmdash setup` again and choose Tablet.")
            return
        if yes("Show the dashboard on the tablet now?"):
            try:
                cli.cmd_push(argparse.Namespace(dir=self.base, demo=False, at=None, battery_pct=None))
            except SystemExit as e:
                say(warn(f"Push failed: {e}"))

    def refresh(self) -> None:
        from rmdash import schedule
        heading("Automatic refresh")
        mins = self.get("schedule", "minutes", 30)
        opts = [15, 20, 30, 60]
        i = pick("Refresh every", [f"{m} minutes" for m in opts], opts.index(mins) if mins in opts else 2)[0]
        self.set("schedule", minutes=opts[i])
        self.save()
        say("While this computer is on, it updates the tablet on the clock (e.g. :00 and :30).\n"
            "When the computer is off, the tablet keeps showing the last page.")
        if sys.platform == "darwin" and any(self.base.is_relative_to(Path.home() / d)
                                            for d in ("Documents", "Desktop", "Downloads")):
            say(warn("macOS will ask once: \"python would like to access files in your Documents folder\". "
                     "Click Allow."))
        if yes("Turn on automatic refresh?"):
            say(schedule.install(self.base, opts[i]))
        else:
            self.todo.append("Turn on automatic refresh: `rmdash schedule install`.")

    def preview(self) -> None:
        from rmdash import cli
        heading("Preview")
        say("Rendering your dashboard (the first time downloads a small headless browser, about a minute)...")
        try:
            cli.cmd_preview(argparse.Namespace(dir=self.base, demo=False, at=None, battery=None, no_open=False))
        except (SystemExit, Exception) as e:  # noqa: BLE001
            say(warn(f"Preview failed: {e}"))
            return
        say("It opened out/preview.png. Morning or night instead? Try "
            + bold("rmdash preview --at 07:30") + " or " + bold("--at 22:30") + ".")


SECTIONS: list[tuple[str, Callable[[Setup], None]]] = [
    ("You, title, city and units", Setup.basics),
    ("Look and screens (morning, night, workday)", Setup.screens),
    ("Calendar", Setup.calendar),
    ("To-do lists (TickTick)", Setup.tasks),
    ("Sports teams", Setup.sports),
    ("Morning headlines", Setup.headlines),
    ("Extras (XKCD, On this day, quotes, air quality)", Setup.extras),
    ("Tablet connection", Setup.tablet),
    ("Automatic refresh", Setup.refresh),
]


def _check_ics(url: str) -> tuple[bool, str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read()
    except Exception as e:  # noqa: BLE001
        return False, type(e).__name__
    if b"BEGIN:VCALENDAR" not in body[:2000]:
        return False, "not an iCal file"
    return True, f"{body.count(b'BEGIN:VEVENT')} events"


def run(base: Path) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # type: ignore[union-attr]
    s = Setup(base)
    say(bold("\nrmdash setup") + " turns your reMarkable into a wall dashboard.\n"
        + dim("Press Enter to accept the value in [brackets]. Ctrl+C stops at any time; "
              "finished sections are already saved."))
    try:
        if not s.cfg.get("location", {}).get("latitude"):
            say("\nLet's set it up. It takes about 10 minutes; every question can be changed later.")
            for _, fn in SECTIONS[:7]:
                fn(s)
                s.save()
            s.preview()
            for _, fn in SECTIONS[7:]:
                fn(s)
        else:
            while True:
                heading("What would you like to change?")
                i = pick("Number (Enter to finish)", [n for n, _ in SECTIONS] + ["Preview", "Everything, in order"],
                         many=True)
                if not i:
                    break
                for j in i:
                    if j < len(SECTIONS):
                        SECTIONS[j][1](s)
                        s.save()
                    elif j == len(SECTIONS):
                        s.preview()
                    else:
                        for _, fn in SECTIONS:
                            fn(s)
                            s.save()
    except (KeyboardInterrupt, EOFError):
        say("\n" + warn("Stopped. Anything not yet saved was discarded."))
        return
    heading("Done")
    for t in s.todo:
        say(f"  • {t}")
    say("Change anything later with " + bold("rmdash setup") + ". Everyday commands:\n"
        "  rmdash preview          see the dashboard on this computer\n"
        "  rmdash push             update the tablet now\n"
        "  rmdash tablet restore   get the normal reMarkable app back (or restart the tablet)")
