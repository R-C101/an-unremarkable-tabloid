"""Talks to the tablet over SSH (paramiko, so it works the same on macOS,
Windows and Linux without relying on a system ssh/scp/sftp).

Safety rules this module follows:
  * Everything we add lives in one folder (default /home/root/rmdash).
  * The only system change is stopping xochitl (the normal reMarkable UI) while
    the dashboard is shown. `restore` starts it again, and so does a reboot.
"""

from __future__ import annotations

import io
import os
import posixpath
import shlex
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
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "rmdash",
                        "-f", str(path)], check=True)
        return
    key = paramiko.RSAKey.generate(3072)
    key.write_private_key_file(str(path))
    Path(str(path) + ".pub").write_text(f"{key.get_name()} {key.get_base64()} rmdash\n")


def load_env(base: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    f = base / ".env"
    if f.exists():
        for ln in f.read_text("utf-8").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, _, v = ln.partition("=")
                env[k.strip()] = v.strip().strip("'\"")
    env.update({k: v for k, v in os.environ.items() if k.startswith("RM_")})
    return env


class Tablet:
    def __init__(self, cfg: dict[str, Any], base: Path):
        env = load_env(base)
        t = cfg.get("tablet", {})
        self.host = env.get("RM_HOST") or t.get("host", "10.11.99.1")
        self.user = env.get("RM_USER") or t.get("user", "root")
        self.password = env.get("RM_PASSWORD")
        self.key_path = Path(os.path.expanduser(t.get("key", str(DEFAULT_KEY))))
        self.remote_dir = t.get("remote_dir", "/home/root/rmdash")
        self.client: paramiko.SSHClient | None = None

    # -- connection -------------------------------------------------------
    def __enter__(self) -> "Tablet":
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
            "echo firmware=$(grep -h REMARKABLE_RELEASE_VERSION /usr/share/remarkable/update.conf "
            "/etc/remarkable/update.conf 2>/dev/null | head -1 | cut -d= -f2);"
            "echo build=$(cat /etc/version 2>/dev/null);"
            "echo xochitl=$(systemctl is-active xochitl);"
            "echo battery=$(cat /sys/class/power_supply/*/capacity 2>/dev/null | head -1);"
            "echo charging=$(cat /sys/class/power_supply/*/status 2>/dev/null | head -1);"
            "echo wifi_ip=$(ip -4 -o addr show wlan0 2>/dev/null | awk '{print $4}');"
            "echo free_home=$(df -h /home | awk 'NR==2{print $4}');"
            f"echo installed=$(test -x {self.remote_dir}/rmdash-show && echo yes || echo no)"
        )
        out = self.run(script, check=False)
        return dict(ln.split("=", 1) for ln in out.splitlines() if "=" in ln)

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
        if not arch.startswith("armv7"):
            raise TabletError(f"This build supports the reMarkable 1/2 (armv7); tablet reports {arch}")
        binary = resources.files("rmdash").joinpath("bin/rmdash-show-armv7").read_bytes()
        self.run(f"mkdir -p {shlex.quote(self.remote_dir)}")
        self.put(binary, posixpath.join(self.remote_dir, "rmdash-show"), mode="755")
        return self.run(f"{shlex.quote(self.remote_dir)}/rmdash-show -info").strip()

    def show(self, png: bytes) -> str:
        d = shlex.quote(self.remote_dir)
        if self.run(f"test -x {d}/rmdash-show && echo yes", check=False).strip() != "yes":
            self.install()
        self.put(png, posixpath.join(self.remote_dir, "dashboard.png"))
        # Stop the normal UI so it doesn't paint over the dashboard, then draw.
        return self.run(
            "if systemctl is-active --quiet xochitl; then systemctl stop xochitl; sleep 2; fi; "
            f"{d}/rmdash-show {d}/dashboard.png"
        ).strip()

    def restore(self) -> None:
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
