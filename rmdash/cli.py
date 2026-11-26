"""Command line: `rmdash <command>`. Run `rmdash -h` for the list."""

from __future__ import annotations

import argparse
import datetime as dt
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


def build(base: Path) -> tuple[Path, Path]:
    cfg = config.load(base / "config.toml")
    ctx = data.collect(cfg, base)
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
    if a.demo:
        from rmdash import demo
        panel, preview = render.render(demo.collect(a.dir), a.dir / "out" / "demo")
    else:
        panel, preview = build(a.dir)
    print(f"Preview: {preview}\nPanel image: {panel}")
    if not a.no_open:
        open_file(preview)


def cmd_push(a: argparse.Namespace, quiet_offline: bool = False) -> None:
    panel, _ = build(a.dir)
    cfg = config.load(a.dir / "config.toml")
    try:
        with device.Tablet(cfg, a.dir) as t:
            t.show(panel.read_bytes())
        log("dashboard updated on the tablet")
    except device.TabletError as e:
        if quiet_offline:
            log(f"tablet not reachable, will try next time ({e})")
            return
        sys.exit(str(e))


def cmd_run(a: argparse.Namespace) -> None:
    cmd_push(a, quiet_offline=True)


def tablet(a: argparse.Namespace) -> device.Tablet:
    cfg = config.load(a.dir / "config.toml") if (a.dir / "config.toml").exists() else config.DEFAULTS
    return device.Tablet(cfg, a.dir)


def cmd_tablet(a: argparse.Namespace) -> None:
    t = tablet(a)
    try:
        with t:
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
                print("Ready. Next: rmdash push")
            elif a.action == "restore":
                t.restore()
                print("Normal reMarkable interface restarted")
            elif a.action == "backup":
                dest = a.dir / "backup" / f"xochitl-{dt.datetime.now():%Y%m%d-%H%M%S}.tar"
                print(f"Saved {t.backup(dest) / 1e6:.1f} MB to {dest}")
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
    s.set_defaults(fn=cmd_preview)

    sub.add_parser("push", help="render and show it on the tablet now").set_defaults(fn=cmd_push)
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
