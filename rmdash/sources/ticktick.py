"""TickTick tasks via the official Open API (free, read-only scope).

One-time setup:
  1. https://developer.ticktick.com -> Manage Apps -> + App Name.
  2. Set its OAuth redirect URL to  http://127.0.0.1:8765/callback
  3. Put the Client ID and Client Secret in .env as
        TICKTICK_CLIENT_ID=...
        TICKTICK_CLIENT_SECRET=...
  4. Run `rmdash ticktick login`, approve in the browser. The token is saved to .env.
"""

from __future__ import annotations

import base64
import datetime as dt
import http.server
import secrets
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from rmdash.data import fmt_time
from rmdash.http import get_json, post_form

AUTH_URL = "https://ticktick.com/oauth/authorize"
TOKEN_URL = "https://ticktick.com/oauth/token"
API = "https://api.ticktick.com/open/v1"
REDIRECT = "http://127.0.0.1:8765/callback"
SCOPE = "tasks:read"


def set_env(base: Path, values: dict[str, str]) -> None:
    """Update KEY=value lines in .env without disturbing the others."""
    f = base / ".env"
    lines = f.read_text("utf-8").splitlines() if f.exists() else []
    for k, v in values.items():
        lines = [ln for ln in lines if not ln.startswith(k + "=")] + [f"{k}={v}"]
    f.write_text("\n".join(lines) + "\n", "utf-8")
    f.chmod(0o600)


def _basic(env: dict[str, str]) -> str:
    raw = f"{env['TICKTICK_CLIENT_ID']}:{env['TICKTICK_CLIENT_SECRET']}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def _save_token(base: Path, tok: dict[str, Any]) -> None:
    vals = {"TICKTICK_TOKEN": tok["access_token"]}
    if tok.get("refresh_token"):
        vals["TICKTICK_REFRESH_TOKEN"] = tok["refresh_token"]
    if tok.get("expires_in"):
        vals["TICKTICK_EXPIRES_AT"] = str(int(time.time() + float(tok["expires_in"])))
    set_env(base, vals)


def login(base: Path, env: dict[str, str]) -> None:
    if not env.get("TICKTICK_CLIENT_ID") or not env.get("TICKTICK_CLIENT_SECRET"):
        raise SystemExit("Add TICKTICK_CLIENT_ID and TICKTICK_CLIENT_SECRET to .env first "
                         "(see rmdash/sources/ticktick.py for the steps).")
    state = secrets.token_urlsafe(16)
    got: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            if q.get("state") == state and "code" in q:
                got["code"] = q["code"]
                msg = "TickTick connected. You can close this tab."
            else:
                msg = "Something went wrong (state mismatch or no code). Try again."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(msg.encode())

        def log_message(self, *a: Any) -> None:
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 8765), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": env["TICKTICK_CLIENT_ID"], "scope": SCOPE, "state": state,
        "redirect_uri": REDIRECT, "response_type": "code"})
    print("Opening TickTick to approve read-only access...\nIf nothing opens, visit:\n" + url)
    webbrowser.open(url)
    deadline = time.time() + 300
    while "code" not in got and time.time() < deadline:
        time.sleep(0.3)
    srv.shutdown()
    if "code" not in got:
        raise SystemExit("Timed out waiting for TickTick approval")
    tok = post_form(TOKEN_URL, {"code": got["code"], "grant_type": "authorization_code",
                                "scope": SCOPE, "redirect_uri": REDIRECT},
                    headers={"Authorization": _basic(env)})
    _save_token(base, tok)
    print("Saved TickTick token to .env")


def _token(base: Path, env: dict[str, str]) -> str:
    exp = float(env.get("TICKTICK_EXPIRES_AT") or 0)
    if exp and exp - time.time() < 86400 and env.get("TICKTICK_REFRESH_TOKEN"):
        tok = post_form(TOKEN_URL, {"grant_type": "refresh_token",
                                    "refresh_token": env["TICKTICK_REFRESH_TOKEN"]},
                        headers={"Authorization": _basic(env)})
        _save_token(base, tok)
        return tok["access_token"]
    return env["TICKTICK_TOKEN"]


def projects(base: Path, env: dict[str, str]) -> list[dict[str, Any]]:
    """Your open TickTick lists (for choosing which to show)."""
    hdr = {"Authorization": "Bearer " + _token(base, env)}
    return [p for p in get_json(f"{API}/project", headers=hdr) if not p.get("closed")]


def _due(t: dict[str, Any], tz: ZoneInfo) -> dt.datetime | None:
    d = t.get("dueDate") or t.get("startDate")
    if not d:
        return None
    # e.g. "2026-11-26T18:30:00.000+0000"
    when = dt.datetime.strptime(d, "%Y-%m-%dT%H:%M:%S.%f%z")
    zone = ZoneInfo(t["timeZone"]) if t.get("timeZone") else tz
    return when.astimezone(zone).astimezone(tz)


def tasks(cfg: dict[str, Any], base: Path, env: dict[str, str], tz: ZoneInfo) -> dict[str, Any] | None:
    tcfg = cfg.get("ticktick", {})
    if not tcfg.get("enabled") or not env.get("TICKTICK_TOKEN"):
        return None
    hdr = {"Authorization": "Bearer " + _token(base, env)}
    projects = get_json(f"{API}/project", headers=hdr)
    wanted = set(tcfg.get("lists", []))  # empty = all lists
    ids = [("inbox", "Inbox")] + [(p["id"], p["name"]) for p in projects
                                  if not p.get("closed") and (not wanted or p["name"] in wanted)]
    if wanted and "Inbox" not in wanted:
        ids = ids[1:]
    today = dt.datetime.now(tz).date()
    items = []
    for pid, pname in ids:
        try:
            data = get_json(f"{API}/project/{pid}/data", headers=hdr)
        except Exception:  # noqa: BLE001 - e.g. inbox id not accepted
            continue
        for t in data.get("tasks", []):
            if t.get("status", 0) != 0:
                continue
            due = _due(t, tz)
            items.append({"title": t.get("title", "").strip(), "list": pname,
                          "priority": t.get("priority", 0), "due": due,
                          "all_day": t.get("isAllDay", True)})
    horizon = int(tcfg.get("days_ahead", 2))

    def label(i: dict[str, Any]) -> str:
        if not i["due"]:
            return ""
        d = i["due"].date()
        if d < today:
            return "Overdue"
        day = "Today" if d == today else ("Tomorrow" if d == today + dt.timedelta(days=1) else d.strftime("%a"))
        return day if i["all_day"] else f"{day} {fmt_time(i['due'])}"

    if tcfg.get("only_due", False):
        items = [i for i in items if i["due"] and i["due"].date() <= today + dt.timedelta(days=horizon)]
    far = dt.datetime.max.replace(tzinfo=tz)
    items.sort(key=lambda i: (i["due"] is None, i["due"] or far, -i["priority"]))
    for i in items:
        i["when"] = label(i)
        i["high"] = i["priority"] >= 5
    order = list(tcfg.get("lists", [])) or list(dict.fromkeys(i["list"] for i in items))
    groups = [{"name": n, "items": [i for i in items if i["list"] == n]} for n in order]
    return {"items": items, "count": len(items), "groups": groups}
