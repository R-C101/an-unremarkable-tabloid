"""Command line: `rmdash <command>`. Run `rmdash -h` for the list."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from rmdash import config, data, device, render, schedule


def log(msg: str) -> None:
    print(f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def open_file(p: Path) -> None:
    if sys.platform == "darwin":
        subprocess.run(["open", str(p)])
    elif os.name == "nt":
        os.startfile(str(p))  # type: ignore[attr-defined]
    elif shutil.which("xdg-open"):
        subprocess.run(["xdg-open", str(p)])


def build(base: Path, battery: dict | None = None, at: dt.time | None = None) -> tuple[Path, Path]:
    cfg = config.load(base / "config.toml")
    ctx = data.collect(cfg, base, battery=battery, at=at)
    for p in ctx["problems"]:
        log(f"warning: {p}")
    return render.render(ctx, base / "out")


def cmd_init(a: argparse.Namespace) -> None:
    base = a.dir
    cfg_path = base / "config.toml"
    if cfg_path.exists() and not a.force:
        sys.exit("config.toml already exists (use --force to overwrite)")
    text = (base / "config.example.toml").read_text("utf-8")
    if a.city:
        place = data.geocode(a.city)
        text = re.sub(r'(?m)^name = .*$', f'name = "{place["name"]}"', text, count=1)
        text = re.sub(r'(?m)^latitude = .*$', f'latitude = {place["latitude"]}', text, count=1)
        text = re.sub(r'(?m)^longitude = .*$', f'longitude = {place["longitude"]}', text, count=1)
        text = re.sub(r'(?m)^timezone = .*$', f'timezone = "{place["timezone"]}"', text, count=1)
        print(f"Location: {place['name']} ({place['latitude']}, {place['longitude']})")
    cfg_path.write_text(text, "utf-8")
    if not (base / "notes.md").exists() and (base / "notes.example.md").exists():
        shutil.copy(base / "notes.example.md", base / "notes.md")
    print(f"Wrote {cfg_path}. Next: rmdash preview")


def cmd_preview(a: argparse.Namespace) -> None:
    battery = {"level": a.battery, "charging": False} if a.battery is not None else None
    if a.demo:  # sample data and a made-up battery level, so screenshots are safe to share
        from rmdash import demo
        panel, preview = render.render(demo.collect(a.dir, battery=battery, at=a.at), a.dir / "out" / "demo")
    else:
        panel, preview = build(a.dir, battery=battery or last_battery(a.dir), at=a.at)
    print(f"Preview: {preview}\nPanel image: {panel}")
    if not a.no_open:
        open_file(preview)


def last_battery(base: Path) -> dict | None:
    f = base / "out" / "battery.json"
    return json.loads(f.read_text()) if f.exists() else None


def cmd_push(a: argparse.Namespace, quiet_offline: bool = False) -> None:
    cfg = config.load(a.dir / "config.toml")
    t = device.Tablet(cfg, a.dir)
    try:
        if quiet_offline:  # scheduled run: only bother while the tablet is in its awake window
            inside, secs = device.window(t.every, t.awake)
            t.connect_when_awake(max_wait=max(secs - 20, 0) if (inside and t.sleep) else 0)
        else:  # by hand: wait for the next window if it's asleep
            t.connect_when_awake(max_wait=t.every + t.awake if t.sleep else 0, say=log)
    except device.TabletError as e:
        if quiet_offline:
            log(f"tablet not reachable, will try next time ({e})")
            return
        sys.exit(str(e))
    try:
        t.busy(True)  # keep it awake while we render and upload
        battery = t.battery()  # read first, so a low battery gets the charge-me screen
        if battery:
            (a.dir / "out").mkdir(exist_ok=True)
            (a.dir / "out" / "battery.json").write_text(json.dumps(battery))
        if getattr(a, "demo", False):  # sample data only: safe to photograph and share
            from rmdash import demo
            fake = {"level": a.battery_pct, "charging": False} if a.battery_pct is not None else None
            panel, _ = render.render(demo.collect(a.dir, battery=fake, at=a.at), a.dir / "out" / "demo")
        else:
            if getattr(a, "battery_pct", None) is not None:
                battery = {"level": a.battery_pct, "charging": False}
            panel, _ = build(a.dir, battery=battery, at=getattr(a, "at", None))
        t.show(panel.read_bytes())
        log("dashboard updated on the tablet" + (" (sleeping until the next refresh)" if t.sleep else ""))
    except device.TabletError as e:
        if quiet_offline:
            log(f"push failed, will try next time ({e})")
            return
        sys.exit(str(e))
    finally:
        try:
            t.busy(False)
        except Exception:  # noqa: BLE001
            pass
        if t.client:
            t.client.close()


def cmd_run(a: argparse.Namespace) -> None:
    cmd_push(a, quiet_offline=True)


def tablet(a: argparse.Namespace) -> device.Tablet:
    cfg = config.load(a.dir / "config.toml") if (a.dir / "config.toml").exists() else config.DEFAULTS
    return device.Tablet(cfg, a.dir)


def cmd_tablet(a: argparse.Namespace) -> None:
    t = tablet(a)
    try:
        t.connect_when_awake(max_wait=t.every + t.awake if t.sleep else 0, say=print)
        with t:
            if a.action in ("setup", "backup"):
                t.busy(True)  # these take a while: don't let it fall asleep mid-way
            if a.action == "info":
                for k, v in t.info().items():
                    print(f"{k:>10}: {v}")
            elif a.action == "setup":
                info = t.info()
                print(f"Found {info.get('model')} ({info.get('arch')}), build {info.get('build')}")
                t.install_key()
                print(f"Installed SSH key {t.key_path} (password no longer needed)")
                dest = a.dir / "backup" / f"xochitl-{dt.datetime.now():%Y%m%d-%H%M%S}.tar"
                size = t.backup(dest)
                print(f"Backed up documents to {dest} ({size / 1e6:.1f} MB)")
                print("Screen:", t.install())
                t.busy(False)
                print("Ready. Next: rmdash push")
            elif a.action == "restore":
                t.restore()
                print("Normal reMarkable interface restarted")
            elif a.action == "backup":
                dest = a.dir / "backup" / f"xochitl-{dt.datetime.now():%Y%m%d-%H%M%S}.tar"
                print(f"Saved {t.backup(dest) / 1e6:.1f} MB to {dest}")
                t.busy(False)
            elif a.action == "uninstall":
                t.uninstall()
                print("Removed rmdash from the tablet and restarted the normal interface")
    except device.TabletError as e:
        sys.exit(str(e))


def cmd_sports(a: argparse.Namespace) -> None:
    from rmdash.sources.sports import search

    rows = search(a.query)
    if not rows:
        sys.exit("No teams found")
    for r in rows:
        print(f'[[sports]]\nname = "{r["name"]}"\nsport = "{r["sport"]}"\n'
              f'league = "{r["league"]}"\nteam_id = {r["team_id"]}\n')
    print("Copy the block you want into config.toml.")


def cmd_ticktick(a: argparse.Namespace) -> None:
    from rmdash.sources import ticktick

    ticktick.login(a.dir, device.load_env(a.dir))



def cmd_schedule(a: argparse.Namespace) -> None:
    if a.action == "install":
        cfg = config.load(a.dir / "config.toml")
        print(schedule.install(a.dir, int(cfg["schedule"]["minutes"])))
    elif a.action == "remove":
        print(schedule.remove())
    else:
        print(schedule.status())


def hhmm(v: str) -> dt.time:
    return dt.time.fromisoformat(v if len(v) > 2 else v + ":00")


def main() -> None:
    p = argparse.ArgumentParser(prog="rmdash", description="reMarkable home dashboard")
    p.add_argument("--dir", type=Path, default=Path.cwd(), help="project folder (default: current)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="create config.toml")
    s.add_argument("--city", help="look up latitude/longitude for this place")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("preview", help="render the dashboard to out/preview.png")
    s.add_argument("--no-open", action="store_true")
    s.add_argument("--demo", action="store_true", help="use sample data (no config or accounts needed)")
    s.add_argument("--at", type=hhmm, help="pretend it's this time, e.g. 07:30, to see the timed screens")
    s.add_argument("--battery", type=int, help="pretend the tablet battery is at this %%")
    s.set_defaults(fn=cmd_preview)

    s = sub.add_parser("push", help="render and show it on the tablet now")
    s.add_argument("--at", type=hhmm, help="pretend it's this time, e.g. 22:00")
    s.add_argument("--demo", action="store_true", help="show the sample dashboard (nothing personal) on the tablet")
    s.add_argument("--battery", dest="battery_pct", type=int, help="pretend the battery is at this %%")
    s.set_defaults(fn=cmd_push)
    sub.add_parser("run", help="what the scheduler runs (push, quiet if offline)").set_defaults(fn=cmd_run)

    s = sub.add_parser("tablet", help="tablet setup and maintenance")
    s.add_argument("action", choices=["info", "setup", "restore", "backup", "uninstall"])
    s.set_defaults(fn=cmd_tablet)

    s = sub.add_parser("sports", help="find a team to follow")
    s.add_argument("action", choices=["search"])
    s.add_argument("query")
    s.set_defaults(fn=cmd_sports)

    s = sub.add_parser("ticktick", help="connect TickTick (one time)")
    s.add_argument("action", choices=["login"])
    s.set_defaults(fn=cmd_ticktick)

    s = sub.add_parser("schedule", help="refresh automatically while this computer is on")
    s.add_argument("action", choices=["install", "remove", "status"])
    s.set_defaults(fn=cmd_schedule)

    a = p.parse_args()
    a.dir = a.dir.resolve()
    a.fn(a)
