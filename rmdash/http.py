"""Tiny JSON-over-HTTP helper (stdlib only)."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

USER_AGENT = "rmdash/0.1"
TIMEOUT = 15


def get_json(url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> Any:
    full = url + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
    req = urllib.request.Request(full, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.load(r)


def post_form(url: str, form: dict[str, str], headers: dict[str, str] | None = None) -> Any:
    body = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "User-Agent": USER_AGENT, "Content-Type": "application/x-www-form-urlencoded", **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.load(r)
