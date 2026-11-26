# CLAUDE.md

Guidance for coding agents working in this repo, including agents that set it up for a new user.

## What this is

`rmdash` turns a reMarkable 1 (and probably a reMarkable 2) into a wall dashboard. A computer
renders an HTML template to a 1404×1872 16-grey PNG, then pushes it over SSH to the tablet.
A tiny Go binary on the tablet writes the image straight to the e-ink framebuffer.
When the computer is off, nothing is pushed and the last image stays on screen (e-ink needs no power to hold it).

```
computer (macOS / Windows / Linux)                     tablet (/home/root/rmdash)
data.py ─► templates/dashboard.html ─► render.py ─► device.py ──SSH──► rmdash-show dashboard.png
(Open-Meteo, iCal, notes.md, quotes.txt)  (Playwright Chromium)  (paramiko)     (/dev/fb0 + MXCFB ioctl)
```

## Layout

- `rmdash/cli.py`: entry point (`rmdash init|preview|push|run|tablet|schedule`).
- `rmdash/data.py`: gathers all data into one dict. Every source fails soft and adds to `ctx["problems"]`.
- `rmdash/templates/dashboard.html`: Jinja2 template. **This is the file to edit for design changes.**
- `rmdash/render.py`: Playwright screenshot, then rotate (landscape) and snap to 16 greys.
- `rmdash/device.py`: SSH via paramiko (no system ssh/scp/sftp needed; uploads go through `cat >`).
- `rmdash/schedule.py`: LaunchAgent (macOS), Task Scheduler (Windows), crontab line (Linux).
- `device/main.go`: source of `rmdash/bin/rmdash-show-armv7`.
- `trmnl-remarkable/`: a git-ignored reference clone of usetrmnl/trmnl-remarkable. It is not part of this project.

## Commands

```sh
uv sync                                   # install deps (Python ≥3.11)
uv run rmdash init --city "Austin, TX"    # writes config.toml (git-ignored)
uv run rmdash preview                     # renders out/preview.png and opens it. Use this to check design changes.
uv run rmdash tablet setup                # installs SSH key, backs up documents, installs binary
uv run rmdash push                        # render and show on tablet now
uv run rmdash schedule install            # refresh every N minutes while the computer is on
uv run rmdash tablet restore              # bring back the normal reMarkable UI

# rebuild the tablet binary after editing device/main.go
cd device && go test ./... && GOOS=linux GOARCH=arm GOARM=7 CGO_ENABLED=0 \
  go build -trimpath -ldflags "-s -w" -o ../rmdash/bin/rmdash-show-armv7 .
```

## Secrets and local files

- `.env` holds `RM_HOST`, `RM_USER` and `RM_PASSWORD` (the tablet's root SSH password). It is git-ignored.
  **Never print, commit or echo its contents.** After `rmdash tablet setup` the key at
  `~/.ssh/remarkable_dashboard` is used and the password is only a fallback.
- `config.toml`, `notes.md`, `out/`, `logs/` and `backup/` are git-ignored. Calendar iCal links in config.toml are secret.

## Tablet safety rules (do not relax)

- Only write inside `/home/root/rmdash` (plus `~/.ssh/authorized_keys` during setup). Don't touch `/usr`, `/etc`,
  the root filesystem, xochitl's files, or the bootloader. Don't install Toltec/XOVI or other system mods.
- The only system change is `systemctl stop xochitl` while the dashboard shows. `rmdash tablet restore`
  or a reboot undoes it. Don't `systemctl disable`/`mask` xochitl.
- Run `rmdash tablet backup` before anything new or risky on the device.
- Tablet over USB: `10.11.99.1`. Wi-Fi IP: see `rmdash tablet info`.

## Hardware facts

- reMarkable 1: i.MX6 SoloLite, armv7l, framebuffer `/dev/fb0` is 1404×1872 visible, RGB565
  (line length is usually 1408 px). Refresh uses `MXCFB_SEND_UPDATE` (0x4048462E), GC16 waveform, full update.
- The user's tablet is a reMarkable 1. Firmware was 3.0.4, then auto-updated to 3.11.2.5 (Nov 2026).
- reMarkable 2 uses a different display path (needs rm2fb), so `rmdash-show` won't drive its screen yet.

## Design notes for the template

- E-ink shows 16 greys. Keep body text pure black. Use grey (`--soft`, `--faint`) only for labels and rules.
- Fonts are bundled in `rmdash/fonts` (Fraunces, Inter; OFL), so renders look the same on every OS.
- Weather icons are inline SVG macros in the template, so nothing is fetched at render time.
- Check every change with `rmdash preview` before pushing.
