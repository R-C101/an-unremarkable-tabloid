"""Runs `rmdash run` every N minutes while the computer is on.

macOS: a LaunchAgent (runs at login and every N minutes; missed runs while the
Mac sleeps happen on wake). Windows: two Task Scheduler tasks (every N minutes,
and at logon). Linux: prints a crontab line.
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

LABEL = "com.rmdash.refresh"
WIN_TASK = "rmdash-refresh"


def command(base: Path) -> list[str]:
    py = sys.executable
    if os.name == "nt":  # pythonw avoids a console window flashing every 30 min
        w = Path(py).with_name("pythonw.exe")
        py = str(w) if w.exists() else py
    return [py, "-m", "rmdash", "--dir", str(base), "run"]


def install(base: Path, minutes: int) -> str:
    cmd = command(base)
    if sys.platform == "darwin":
        logs = base / "logs"
        logs.mkdir(exist_ok=True)
        plist = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
        plist.parent.mkdir(parents=True, exist_ok=True)
        plist.write_bytes(plistlib.dumps({
            "Label": LABEL, "ProgramArguments": cmd, "WorkingDirectory": str(base),
            "StartInterval": minutes * 60, "RunAtLoad": True,
            "StandardOutPath": str(logs / "rmdash.log"), "StandardErrorPath": str(logs / "rmdash.log"),
        }))
        uid = os.getuid()
        subprocess.run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"], capture_output=True)
        subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(plist)], check=True)
        msg = f"Installed LaunchAgent {plist} (every {minutes} min, and at login)"
        home = Path.home()
        if any(base.is_relative_to(home / d) for d in ("Documents", "Desktop", "Downloads")):
            msg += ("\nNOTE: this folder is in a macOS-protected location. The first background run will"
                    "\nshow a prompt like 'python would like to access files in your Documents folder'."
                    "\nClick Allow, or the refresh will wait forever.")
        return msg
    if os.name == "nt":
        tr = subprocess.list2cmdline(cmd)
        subprocess.run(["schtasks", "/Create", "/F", "/TN", WIN_TASK, "/SC", "MINUTE",
                        "/MO", str(minutes), "/TR", tr], check=True)
        subprocess.run(["schtasks", "/Create", "/F", "/TN", WIN_TASK + "-logon", "/SC", "ONLOGON",
                        "/TR", tr], check=True)
        return f"Created scheduled tasks {WIN_TASK} (every {minutes} min) and {WIN_TASK}-logon"
    line = f"*/{minutes} * * * * cd {base} && {subprocess.list2cmdline(cmd)} >> {base}/logs/rmdash.log 2>&1"
    return "Add this line with `crontab -e` (plus an @reboot line if you like):\n" + line


def remove() -> str:
    if sys.platform == "darwin":
        plist = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], capture_output=True)
        plist.unlink(missing_ok=True)
        return "Removed the LaunchAgent"
    if os.name == "nt":
        for t in (WIN_TASK, WIN_TASK + "-logon"):
            subprocess.run(["schtasks", "/Delete", "/F", "/TN", t], capture_output=True)
        return "Removed the scheduled tasks"
    return "Remove the rmdash line with `crontab -e`"


def status() -> str:
    if sys.platform == "darwin":
        r = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"], capture_output=True, text=True)
        return "Scheduled (LaunchAgent loaded)" if r.returncode == 0 else "Not scheduled"
    if os.name == "nt" and shutil.which("schtasks"):
        r = subprocess.run(["schtasks", "/Query", "/TN", WIN_TASK], capture_output=True, text=True)
        return "Scheduled" if r.returncode == 0 else "Not scheduled"
    return "Check `crontab -l`"
