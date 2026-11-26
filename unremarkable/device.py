"""Talks to the tablet over SSH (paramiko, so it works the same on macOS,
Windows and Linux without relying on a system ssh/scp/sftp).

Safety rules this module follows:
  * Everything we add lives in one folder (default /home/root/tabloid).
  * The only system change is stopping xochitl (the normal reMarkable UI) while
    the dashboard is shown. `restore` starts it again, and so does a reboot.
"""

from __future__ import annotations

import datetime as dt
import io
import os
import posixpath
import re
import shlex
import time
from importlib import resources
from pathlib import Path
from typing import Any

import paramiko

DEFAULT_KEY = Path.home() / ".ssh" / "remarkable_dashboard"


class TabletError(RuntimeError):
    pass


def make_key(path: Path) -> None:
    """Create a dedicated key pair: ssh-keygen (ed25519) if present, else paramiko RSA."""
    import shutil
    import subprocess

    path.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which("ssh-keygen"):
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "tabloid",
                        "-f", str(path)], check=True)
        return
    key = paramiko.RSAKey.generate(3072)
    key.write_private_key_file(str(path))
    Path(str(path) + ".pub").write_text(f"{key.get_name()} {key.get_base64()} tabloid\n")


def load_env(base: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    f = base / ".env"
    if f.exists():
        for ln in f.read_text("utf-8").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, _, v = ln.partition("=")
                v = v.strip()
                if v[:1] in "'\"" and v[:1] and v.count(v[0]) >= 2:
                    v = v[1:v.index(v[0], 1)]          # quoted: keep everything inside
                else:
                    v = re.split(r"\s+#", v, maxsplit=1)[0]  # unquoted: drop " # comment"
                env[k.strip()] = v
    env.update({k: v for k, v in os.environ.items() if k.startswith(("RM_", "WAQI_", "TICKTICK_"))})
    return env


SLEEP_UNIT = "tabloid-sleep"


def local_offset() -> int:
    """This computer's UTC offset in seconds (DST-aware), so wake windows follow local time."""
    return int(dt.datetime.now().astimezone().utcoffset().total_seconds())  # type: ignore[union-attr]


def window(every: int, awake: int, now: float | None = None) -> tuple[bool, float]:
    """(inside an awake window?, seconds until it ends / until the next one starts)."""
    now = time.time() if now is None else now
    into = (now + local_offset()) % every
    return (True, awake - into) if into < awake else (False, every - into)


def unsupported(model: str, arch: str) -> str | None:
    """Why tabloid can't drive this tablet's screen yet, or None if it can (reMarkable 1)."""
    if "reMarkable 2" in model:
        return ("This is a reMarkable 2. Its screen isn't driven through the normal framebuffer, so tabloid "
                "can't draw on it yet. Nothing was changed. See README 'Which reMarkable?'.")
    if not arch.startswith("armv7") or ("reMarkable" in model and "reMarkable 1" not in model):
        return (f"This tablet ({model or 'unknown model'}, {arch}) isn't supported yet; only the reMarkable 1 is. "
                "Nothing was changed. See README 'Which reMarkable?'.")
    return None


class Tablet:
    def __init__(self, cfg: dict[str, Any], base: Path):
        env = load_env(base)
        t = cfg.get("tablet", {})
        self.every = int(cfg.get("schedule", {}).get("minutes", 30)) * 60
        self.sleep = bool(t.get("sleep", True))
        self.awake = int(t.get("awake_seconds", 180))
        self.host = env.get("RM_HOST") or t.get("host", "10.11.99.1")
        self.user = env.get("RM_USER") or t.get("user", "root")
        self.password = env.get("RM_PASSWORD")
        self.key_path = Path(os.path.expanduser(t.get("key", str(DEFAULT_KEY))))
        self.remote_dir = t.get("remote_dir", "/home/root/tabloid")
        self.client: paramiko.SSHClient | None = None

    # -- connection -------------------------------------------------------
    def __enter__(self) -> "Tablet":
        if not self.client:
            self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        if self.client:
            self.client.close()

    def connect(self, timeout: float = 8) -> None:
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs: dict[str, Any] = dict(hostname=self.host, username=self.user, timeout=timeout,
                                      banner_timeout=timeout, auth_timeout=timeout,
                                      allow_agent=False, look_for_keys=False)
        try:
            if self.key_path.exists():
                try:
                    c.connect(key_filename=str(self.key_path), **kwargs)
                    self.client = c
                    return
                except paramiko.AuthenticationException:
                    if not self.password:
                        raise
            if not self.password:
                raise TabletError("No SSH key installed yet and no RM_PASSWORD in .env")
            c.connect(password=self.password, **kwargs)
            self.client = c
        except (OSError, paramiko.SSHException) as e:
            raise TabletError(f"Cannot reach the tablet at {self.host}: {e}") from e

    def connect_when_awake(self, max_wait: float, say: Any = None) -> None:
        """Keep trying until the tablet answers (it may be asleep until its next window)."""
        deadline = time.time() + max_wait
        told = False
        while True:
            try:
                self.connect()
                return
            except TabletError:
                if time.time() >= deadline:
                    raise
                if say and not told and self.sleep:
                    inside, secs = window(self.every, self.awake)
                    wait = 0 if inside else secs
                    when = (dt.datetime.now() + dt.timedelta(seconds=wait)).strftime("%H:%M")
                    say(f"The tablet is asleep. It wakes by itself at {when}, or press its power button "
                        "to wake it now (it then stays awake 5 minutes). Waiting... (Ctrl+C to stop)")
                    told = True
                time.sleep(5)

    def run(self, command: str, check: bool = True, stdin: bytes | None = None) -> str:
        assert self.client, "not connected"
        chan = self.client.get_transport().open_session()  # type: ignore[union-attr]
        chan.exec_command(command)
        if stdin is not None:
            chan.sendall(stdin)
            chan.shutdown_write()
        out = io.BytesIO()
        err = io.BytesIO()
        while True:
            if chan.recv_ready():
                out.write(chan.recv(65536))
            if chan.recv_stderr_ready():
                err.write(chan.recv_stderr(65536))
            if chan.exit_status_ready() and not chan.recv_ready() and not chan.recv_stderr_ready():
                break
        code = chan.recv_exit_status()
        text = out.getvalue().decode("utf-8", "replace")
        if check and code != 0:
            raise TabletError(f"`{command}` failed ({code}): {err.getvalue().decode(errors='replace').strip()}")
        return text

    def put(self, data: bytes, remote: str, mode: str = "644") -> None:
        """Upload via `cat`, atomically (write to .tmp, then rename)."""
        tmp = remote + ".tmp"
        self.run(f"cat > {shlex.quote(tmp)} && chmod {mode} {shlex.quote(tmp)} && "
                 f"mv {shlex.quote(tmp)} {shlex.quote(remote)}", stdin=data)

    # -- operations -------------------------------------------------------
    def info(self) -> dict[str, str]:
        script = (
            "echo model=$(cat /sys/devices/soc0/machine 2>/dev/null);"
            "echo arch=$(uname -m);"
            "echo firmware=$( (grep -h '^IMG_VERSION' /etc/os-release; grep -h REMARKABLE_RELEASE_VERSION "
            "/usr/share/remarkable/update.conf) 2>/dev/null | head -1 | cut -d= -f2 | tr -d '\"');"
            "echo build=$(cat /etc/version 2>/dev/null);"
            "echo xochitl=$(systemctl is-active xochitl);"
            "for d in /sys/class/power_supply/*; do [ -f $d/capacity ] && "
            "echo battery=$(cat $d/capacity)% && echo charging=$(cat $d/status) && break; done;"
            "echo wifi_ip=$(ip -4 -o addr show wlan0 2>/dev/null | awk '{print $4}');"
            "echo free_home=$(df -h /home | awk 'NR==2{print $4}');"
            f"echo installed=$(test -x {self.remote_dir}/tabloid-show && echo yes || echo no);"
            f"echo sleep_loop=$(systemctl is-active {SLEEP_UNIT})"
        )
        out = self.run(script, check=False)
        return dict(ln.split("=", 1) for ln in out.splitlines() if "=" in ln)

    def battery(self) -> dict[str, Any] | None:
        """{'level': 0-100, 'charging': bool}, read from the fuel gauge in /sys (read-only)."""
        out = self.run("for d in /sys/class/power_supply/*; do [ -f $d/capacity ] && "
                       "echo $(cat $d/capacity) $(cat $d/status) && break; done", check=False).split()
        if not out or not out[0].isdigit():
            return None
        return {"level": int(out[0]), "charging": len(out) > 1 and out[1] in ("Charging", "Full")}

    def install_key(self) -> None:
        pub = Path(str(self.key_path) + ".pub")
        if not self.key_path.exists():
            make_key(self.key_path)
        line = pub.read_text().strip()
        self.run("mkdir -p ~/.ssh && chmod 700 ~/.ssh && touch ~/.ssh/authorized_keys && "
                 f"(grep -qxF {shlex.quote(line)} ~/.ssh/authorized_keys || "
                 f"echo {shlex.quote(line)} >> ~/.ssh/authorized_keys) && chmod 600 ~/.ssh/authorized_keys")

    def install(self) -> str:
        arch = self.run("uname -m").strip()
        why = unsupported(self.run("cat /sys/devices/soc0/machine 2>/dev/null", check=False).strip(), arch)
        if why:
            raise TabletError(why)
        binary = resources.files("unremarkable").joinpath("bin/tabloid-show-armv7").read_bytes()
        self.run(f"mkdir -p {shlex.quote(self.remote_dir)}")
        self.put(binary, posixpath.join(self.remote_dir, "tabloid-show"), mode="755")
        return self.run(f"{shlex.quote(self.remote_dir)}/tabloid-show -info").strip()

    def busy(self, on: bool) -> None:
        """While a push is in progress the sleep loop stays awake."""
        f = shlex.quote(posixpath.join(self.remote_dir, "busy"))
        self.run(f"mkdir -p {shlex.quote(self.remote_dir)} && touch {f}" if on else f"rm -f {f}", check=False)

    def show(self, png: bytes) -> str:
        d = shlex.quote(self.remote_dir)
        if self.run(f"test -x {d}/tabloid-show && echo yes", check=False).strip() != "yes":
            self.install()
        self.put(png, posixpath.join(self.remote_dir, "dashboard.png"))
        # Stop the normal UI so it doesn't paint over the dashboard, then draw.
        out = self.run(
            "if systemctl is-active --quiet xochitl; then systemctl stop xochitl; sleep 2; fi; "
            f"{d}/tabloid-show {d}/dashboard.png"
        ).strip()
        if self.sleep:
            self.start_sleeping()
        else:
            self.stop_sleeping()
        return out

    def start_sleeping(self) -> None:
        """(Re)start the sleep loop as a transient unit: it disappears on reboot."""
        script = resources.files("unremarkable").joinpath("bin/sleep-loop.sh").read_bytes()
        path = posixpath.join(self.remote_dir, "sleep-loop.sh")
        self.put(str(local_offset()).encode(), posixpath.join(self.remote_dir, "offset"))
        current = self.run(f"cat {shlex.quote(path)} 2>/dev/null", check=False).encode()
        active = self.run(f"systemctl is-active {SLEEP_UNIT}", check=False).strip() == "active"
        args = f"{self.every} {self.awake}"
        running_args = self.run(f"systemctl show -p ExecStart --value {SLEEP_UNIT} 2>/dev/null", check=False)
        if active and current == script and f"sleep-loop.sh {args} " in running_args + " ":
            return
        self.stop_sleeping()
        self.put(script, path, mode="755")
        self.run(f"systemd-run --unit={SLEEP_UNIT} --collect /bin/sh {shlex.quote(path)} {args}")

    def stop_sleeping(self) -> None:
        self.run(f"systemctl stop {SLEEP_UNIT} 2>/dev/null; systemctl reset-failed {SLEEP_UNIT} 2>/dev/null; true",
                 check=False)

    def restore(self) -> None:
        self.stop_sleeping()
        self.run("systemctl start xochitl")

    def backup(self, dest: Path) -> int:
        """Copy the tablet's documents folder to `dest` as a tar file."""
        assert self.client
        dest.parent.mkdir(parents=True, exist_ok=True)
        chan = self.client.get_transport().open_session()  # type: ignore[union-attr]
        chan.exec_command("tar -C /home/root/.local/share/remarkable -cf - xochitl")
        size = 0
        with open(dest, "wb") as f:
            while True:
                chunk = chan.recv(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                size += len(chunk)
        if chan.recv_exit_status() != 0:
            raise TabletError("backup failed")
        return size

    def uninstall(self) -> None:
        self.restore()
        self.run(f"rm -rf {shlex.quote(self.remote_dir)}")
