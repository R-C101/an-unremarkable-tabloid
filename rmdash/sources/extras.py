"""Small daily modules: XKCD, Wikipedia's "On this day", and RSS/Atom headlines.
All free, no keys."""

from __future__ import annotations

import base64
import datetime as dt
import html
import re
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

from rmdash.http import TIMEOUT, USER_AGENT, get_json


def _get(url: str, tries: int = 2) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.read()
        except Exception:  # noqa: BLE001 - one retry for flaky networks
            if i == tries - 1:
                raise
    raise AssertionError


def xkcd() -> dict[str, Any]:
    """Latest comic. The image is embedded as a data: URI so the render needs no network."""
    c = get_json("https://xkcd.com/info.0.json")
    img = None
    for url in (re.sub(r"\.png$", "_2x.png", c["img"]), c["img"]):  # 2x is sharper when it exists
        try:
            img = _get(url)
            break
        except Exception:  # noqa: BLE001
            continue
    if img is None:
        raise RuntimeError("xkcd image unavailable")
    kind = "png" if img[:4] == b"\x89PNG" else "jpeg"
    return {"num": c["num"], "title": c.get("safe_title") or c.get("title", ""), "alt": c.get("alt", ""),
            "src": f"data:image/{kind};base64,{base64.b64encode(img).decode()}"}


def on_this_day(day: dt.date, n: int = 3, lang: str = "en") -> list[dict[str, Any]]:
    d = get_json(f"https://api.wikimedia.org/feed/v1/wikipedia/{lang}/onthisday/selected/{day:%m}/{day:%d}")
    items = sorted(d.get("selected", []), key=lambda x: x.get("year", 0))
    # Spread picks across history rather than taking the n most recent.
    if len(items) > n:
        step = len(items) / n
        items = [items[int(i * step)] for i in range(n)]
    return [{"year": x.get("year"), "text": x.get("text", "")} for x in items]


def _text(el: ET.Element | None) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", (el.text or "") if el is not None else "")).strip()


def headlines(feeds: list[dict[str, Any] | str], per_feed: int = 4) -> list[dict[str, Any]]:
    """[{name, items: [{title, source}]}] for each RSS or Atom feed."""
    out, failed = [], None
    for f in feeds:
        f = {"url": f} if isinstance(f, str) else f
        try:
            root = ET.fromstring(_get(f["url"]))
        except Exception as e:  # noqa: BLE001 - skip a dead feed, keep the others
            failed = e
            continue
        atom = "{http://www.w3.org/2005/Atom}"
        entries = root.findall(".//item") or root.findall(f".//{atom}entry")
        name = f.get("name") or _text(root.find("channel/title")) or _text(root.find(f"{atom}title"))
        items: list[dict[str, Any]] = []
        seen: list[set[str]] = []
        for e in entries:
            if len(items) >= per_feed:
                break
            title = _text(e.find("title")) or _text(e.find(f"{atom}title"))
            source = _text(e.find("source"))
            if source and title.endswith(" - " + source):  # Google News appends " - Publisher"
                title = title[: -len(source) - 3]
            words = set(re.findall(r"\w{4,}", title.lower()))
            if not title or any(len(words & w) >= 0.5 * min(len(words), len(w)) for w in seen if w):
                continue  # same story from another outlet
            seen.append(words)
            items.append({"title": title, "source": source})
        out.append({"name": name, "items": items})
    if failed and not out:
        raise failed
    return out
