# CLAUDE.md

Guidance for coding agents working in this repo, including agents that set it up for a new user.

## What this is

**An Unremarkable Tabloid** (package `unremarkable`, command `tabloid`) turns a reMarkable 1 (and probably a reMarkable 2) into a wall dashboard. A computer
renders an HTML template to a 1404×1872 16-grey PNG, then pushes it over SSH to the tablet.
A tiny Go binary on the tablet writes the image straight to the e-ink framebuffer.
When the computer is off, nothing is pushed and the last image stays on screen (e-ink needs no power to hold it).

```
computer (macOS / Windows / Linux)                     tablet (/home/root/tabloid)
data.py ─► templates/dashboard.html ─► render.py ─► device.py ──SSH──► tabloid-show dashboard.png
(Open-Meteo, iCal, notes.md, quotes.txt)  (Playwright Chromium)  (paramiko)     (/dev/fb0 + MXCFB ioctl)
```

## Layout

- `unremarkable/cli.py`: entry point (`tabloid setup|init|preview|push|run|tablet|schedule`).
- `unremarkable/wizard.py`: `tabloid setup`, the interactive, re-runnable setup (writes config.toml and .env).
  `install.sh` / `install.ps1` / `install.bat` install uv and dependencies, then run it.
- `unremarkable/data.py`: gathers all data into one dict. Every source fails soft and adds to `ctx["problems"]`.
- `unremarkable/templates/dashboard.html`: Jinja2 template. **This is the file to edit for design changes.**
- `unremarkable/render.py`: Playwright screenshot, then rotate (landscape) and snap to 16 greys.
- `unremarkable/device.py`: SSH via paramiko (no system ssh/scp/sftp needed; uploads go through `cat >`).
- `unremarkable/schedule.py`: LaunchAgent (macOS), Task Scheduler (Windows), crontab line (Linux).
- `device/main.go`: source of `unremarkable/bin/tabloid-show-armv7`.
- `trmnl-remarkable/`: a git-ignored reference clone of usetrmnl/trmnl-remarkable. It is not part of this project.

## Setup playbook (for agents setting this up for someone)

Humans without an agent use `sh install.sh` / `install.bat` → `tabloid setup` (the wizard). It reads stdin, so don't
drive it from an agent; follow the steps below instead.

Work through these in order, and tell the user what each step is for. Never print `.env` or calendar links back to them.

1. `uv sync`, then `uv run tabloid preview --demo --no-open` to check the toolchain. The first run downloads Chromium.
2. Ask for their city and a dashboard title, then run `uv run tabloid init --city "<city>"`. Set `title`, units and `rotate` in config.toml.
3. Ask which modules they want (weather/AQI on by default; calendar, TickTick, sports, notes, quotes). For each one, follow
   the matching README section. Secrets go in `.env`, created by copying `.env.example`; settings go in config.toml.
   Sports: `uv run tabloid sports search "<team>"`, then paste the block. TickTick: they create the developer app, then
   `uv run tabloid ticktick login` (it opens a browser; run it in the background and wait for "Saved").
4. `uv run tabloid preview` and show them `out/preview.png`. Iterate on the design until they're happy.
5. Tablet: they read the SSH password from **Settings → Help → Copyrights and licenses**. Put it in `.env` as
   `RM_PASSWORD` along with `RM_HOST` (`10.11.99.1` over USB, otherwise the Wi-Fi IP). Then run `uv run tabloid tablet setup`,
   which installs the key, backs up their notebooks and installs the binary. Then `uv run tabloid push`, and ask them to confirm the screen.
6. `uv run tabloid schedule install`. On macOS, if the repo is under Documents/Desktop/Downloads, warn them about the
   one-time "access files" prompt before it appears.
7. Tell them how to get the normal tablet UI back: `uv run tabloid tablet restore`, or a restart.

## Commands

```sh
uv sync                                   # install deps (Python ≥3.11)
uv run tabloid init --city "Austin, TX"    # writes config.toml (git-ignored)
uv run tabloid preview                     # renders out/preview.png and opens it. Use this to check design changes.
uv run tabloid preview --demo              # sample data, no accounts needed: use for README/bug-report screenshots
uv run tabloid tablet setup                # installs SSH key, backs up documents, installs binary
uv run tabloid push                        # render and show on tablet now
uv run tabloid schedule install            # refresh every N minutes while the computer is on
uv run tabloid tablet restore              # bring back the normal reMarkable UI

# rebuild the tablet binary after editing device/main.go
cd device && go test ./... && GOOS=linux GOARCH=arm GOARM=7 CGO_ENABLED=0 \
  go build -trimpath -ldflags "-s -w" -o ../unremarkable/bin/tabloid-show-armv7 .
```

## Secrets and local files

- `.env` holds `RM_HOST`, `RM_USER` and `RM_PASSWORD` (the tablet's root SSH password). It is git-ignored.
  **Never print, commit or echo its contents.** After `tabloid tablet setup` the key at
  `~/.ssh/remarkable_dashboard` is used and the password is only a fallback.
- `.env.example` documents every variable. `load_env` also accepts `RM_*`, `WAQI_*` and `TICKTICK_*` from the environment,
  and supports quoted values and trailing `# comments`.
- `config.toml`, `notes.md`, `out/`, `logs/` and `backup/` are git-ignored. Calendar iCal links in config.toml are secret.

## Tablet safety rules (do not relax)

- Only write inside `/home/root/tabloid` (plus `~/.ssh/authorized_keys` during setup). Don't touch `/usr`, `/etc`,
  the root filesystem, xochitl's files, or the bootloader. Don't install Toltec/XOVI or other system mods.
- The only system changes are `systemctl stop xochitl` while the dashboard shows, and the sleep loop: a transient
  `systemd-run --unit=tabloid-sleep` unit running `/home/root/tabloid/sleep-loop.sh`. That loop writes only to kernel
  runtime switches (`/sys/class/rtc/rtc0/wakealarm`, `/sys/power/state`). Transient units live in /run and vanish on reboot,
  so `tabloid tablet restore` or a reboot undoes everything. Don't `systemctl disable`/`mask` xochitl, and never install
  a persistent unit file.
- Run `tabloid tablet backup` before anything new or risky on the device.
- Tablet over USB: `10.11.99.1`. Wi-Fi IP: see `tabloid tablet info`.

## Timed screens

`unremarkable/screens.py` picks `morning` / `day` / `night` / `lowbattery` from `[screens]` windows and the battery. The template
branches on `screen`. Only the sources a screen shows are fetched. `--at HH:MM` and `--battery N` (on preview and push)
simulate time and battery. `--demo` uses `unremarkable/demo.py` sample data: use it for anything that will be shared.

## Battery and sleep

With xochitl stopped the rM1 never suspends by itself, so an always-awake tablet lasts hours (measured Nov 2026:
100% → 55% in about 3.5 h). Since then `[tablet] sleep = true` (the default) runs the sleep loop:

- Wake windows are the first `awake_seconds` (180) after every `schedule.minutes` boundary of local time. The computer
  writes its UTC offset to `/home/root/tabloid/offset` on every push.
- The scheduled job (LaunchAgent `StartCalendarInterval` on :00/:30, schtasks `/ST` aligned, cron `*/N`) connects with
  retries until the window ends. During a push it touches `/home/root/tabloid/busy`, which stops the loop sleeping
  (it's ignored once 5 minutes old). `touch /home/root/tabloid/hold` keeps it awake for maintenance.
  A power-button wake (resumed >30 s before the alarm) keeps it awake 300 s. No remote wake: Wi-Fi is off in suspend.
- Manual commands (`push`, `tablet …`) wait for the next window via `Tablet.connect_when_awake`.
- Verified on rM1 3.29: `echo mem > /sys/power/state` with an RTC alarm suspends (deep), resumes on time, Wi-Fi
  reconnects on the same IP within seconds, and the framebuffer is unchanged (md5 before = after).

## Hardware facts

- reMarkable 1: i.MX6 SoloLite, armv7l, framebuffer `/dev/fb0` is 1404×1872 visible, RGB565
  (line length is usually 1408 px). Refresh uses `MXCFB_SEND_UPDATE` (0x4048462E), GC16 waveform, full update.
- Tested on a reMarkable 1 on firmware 3.29.1.0 (kernel 5.4.70). Verified working over Wi-Fi SSH (Nov 2026).
  Stopping xochitl leaves Wi-Fi (wpa_supplicant) up. xochitl is Restart=on-failure, so a clean stop stays stopped.
- reMarkable 2 uses a different display path (needs rm2fb), so `tabloid-show` won't drive its screen yet.
  Paper Pro / Move: aarch64, colour panel, SSH only in developer mode (which factory-resets). `device.unsupported()`
  makes `tablet setup` refuse both before changing anything.

## Design notes for the template

- E-ink shows 16 greys. Keep body text pure black. Use grey (`--soft`, `--faint`) only for labels and rules.
- Fonts are bundled in `unremarkable/fonts` (Fraunces, Inter; OFL), so renders look the same on every OS.
- Weather icons are inline SVG macros in the template, so nothing is fetched at render time.
- Check every change with `tabloid preview` before pushing.

## macOS gotcha

If the repo is under ~/Documents, ~/Desktop or ~/Downloads, the LaunchAgent's first run blocks on a TCC
prompt ("python would like to access files in your Documents folder"). The user must click Allow. A stuck job
shows `last exit code = (never exited)` in `launchctl print gui/$UID/com.tabloid.refresh`, and `sample <pid>`
shows it parked in `open()`.

## Data sources (all free)

| Feature | Source | Key? | Status |
|---|---|---|---|
| Weather, hourly, 5-day, sunrise/sunset | Open-Meteo forecast | no | built |
| Air quality (modelled) | Open-Meteo air-quality | no | built (underestimates Delhi) |
| Air quality (ground station) | WAQI `api.waqi.info/feed/geo:lat;lon` | free token, `WAQI_TOKEN` in .env | built, needs token |
| Calendar | any iCal/ICS URL (Google secret address, iCloud, Outlook) | no | built |
| Tasks | TickTick Open API, `tabloid ticktick login` (OAuth, tasks:read) | free dev app | built, needs login |
| Sports, any ESPN team (soccer, NBA, NFL, MLB, NHL, college) | ESPN public site API, `tabloid sports search` | no | built |
| XKCD (morning, night) | `xkcd.com/info.0.json`, image embedded as a data: URI | no | built |
| Headlines (morning) | any RSS/Atom feed (`sources/extras.py`), near-duplicates dropped | no | built |
| On this day (night) | `api.wikimedia.org/feed/v1/wikipedia/en/onthisday/selected/MM/DD` | no | built |
| Today at a glance (day) | computed (`data.glance`): next meeting, task counts, progress bars | no | built |
| Battery + low-battery screen | `/sys/class/power_supply/*/capacity` over SSH, read before render | no | built |
| Notes / quotes | local `notes.md` / `quotes.txt` | no | built |

## Roadmap (agreed with the user, Nov 2026)

1. **Setup widget for non-technical users (do later, after the feature set settles).** A simple local web page
   (or the installer UI) that lists every module with a checkbox: weather, AQI, calendar, TickTick, sports
   team picker, cricket, etc. It writes config.toml and .env, walks through tablet pairing (password →
   key) and the OAuth logins, and installs the schedule. Target: no terminal needed. Ship for macOS and Windows.
2. Candidate modules, all free:
   - Cricket: ESPN's `sports/cricket/scorepanel` (no key) has live and scheduled matches (verified Nov 2026). Team-schedule paths 404, so filter by team name.
   - Holidays and festivals: Google public holiday ICS (e.g. Indian holidays). Already works via `calendar.ics_urls`.
   - Countdowns and birthdays (local config), moon phase (computed), UV index and rain nowcast (Open-Meteo).
   - Currency (Frankfurter, no key), crypto (CoinGecko), indices (unofficial Yahoo, fragile).
   - Headlines via RSS, Hacker News top stories, Wikipedia "On this day" (Wikimedia feed API).
   - Picture of the day dithered to 16 greys: NASA APOD (DEMO_KEY) or Met Museum public-domain art. XKCD.
   - F1 next race (jolpica-f1, no key), GitHub contribution graph, Wi-Fi guest QR code (local),
     tablet battery in the footer.
   Researched list with verified endpoints: docs/module-ideas.md.
3. Cricket and multi-team sports layout, and a portrait layout pass.
4. Pull mode (the tablet fetches the PNG itself) for setups away from the computer. Sleep between refreshes is done.
