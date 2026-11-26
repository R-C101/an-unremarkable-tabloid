"""HTML -> PNG at the panel's exact size, converted to the panel's 16 greys."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from importlib import resources
from pathlib import Path
from typing import Any

import jinja2
from PIL import Image

PANEL_W, PANEL_H = 1404, 1872  # reMarkable 1 and 2, portrait, 226 dpi


def html(ctx: dict[str, Any]) -> tuple[str, int, int]:
    cfg = ctx["cfg"]
    landscape = cfg["dashboard"]["orientation"] == "landscape"
    w, h = (PANEL_H, PANEL_W) if landscape else (PANEL_W, PANEL_H)
    pkg = resources.files("unremarkable")
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(pkg / "templates")),
                             autoescape=jinja2.select_autoescape(["html"]))
    tpl = env.get_template(cfg["dashboard"].get("template", "dashboard.html"))
    fonts = Path(str(pkg / "fonts")).resolve().as_uri()
    return tpl.render(**ctx, width=w, height=h, fonts=fonts,
                      orientation="landscape" if landscape else "portrait"), w, h


def screenshot(page_html: str, w: int, h: int) -> Image.Image:
    from playwright.sync_api import Error, sync_playwright

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "dashboard.html"
        src.write_text(page_html, "utf-8")
        png = Path(tmp) / "shot.png"
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except Error as e:
                if "Executable doesn't exist" not in str(e):
                    raise
                print("First run: downloading the headless browser (one time)...", file=sys.stderr)
                subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
                browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
            page.goto(src.as_uri())
            page.evaluate("document.fonts.ready")
            page.wait_for_selector("body[data-ready]", timeout=10_000)
            page.screenshot(path=str(png))
            browser.close()
        return Image.open(png).convert("L")


def to_panel(img: Image.Image, cfg: dict[str, Any]) -> Image.Image:
    if cfg["dashboard"]["orientation"] == "landscape":
        img = img.rotate(int(cfg["dashboard"].get("rotate", 90)), expand=True)
    if img.size != (PANEL_W, PANEL_H):
        raise ValueError(f"rendered {img.size}, expected {(PANEL_W, PANEL_H)}")
    # Snap to the 16 levels the panel can show, so what you preview is what you get.
    return img.point(lambda v: round(v / 17) * 17)


def render(ctx: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    page_html, w, h = html(ctx)
    shot = screenshot(page_html, w, h)
    out_dir.mkdir(parents=True, exist_ok=True)
    preview = out_dir / "preview.png"  # as you'd see it on the wall
    shot.point(lambda v: round(v / 17) * 17).save(preview, optimize=True)
    panel = out_dir / "dashboard.png"  # as the framebuffer wants it
    to_panel(shot, ctx["cfg"]).save(panel, optimize=True)
    (out_dir / "dashboard.html").write_text(page_html, "utf-8")
    return panel, preview
