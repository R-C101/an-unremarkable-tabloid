# Contributing

Thanks for helping. Bug reports, new modules, design tweaks and support for more tablets are all welcome.

## Dev setup

```sh
uv sync
uv run tabloid preview --demo     # renders out/demo/preview.png with sample data, so no tablet or accounts are needed
```

You don't need a reMarkable to work on data sources or the design. `preview` and `preview --demo` never touch a device.

## Adding a module

1. Put the fetching code in `unremarkable/sources/<name>.py`. It should return plain dicts and lists, and raise on failure.
2. Call it from `collect()` in `unremarkable/data.py` inside a `try`. On failure, add a short message to `ctx["problems"]`,
   so one dead API never blanks the page.
3. Add defaults to `unremarkable/config.py`, a commented example to `config.example.toml`, and any secret to `.env.example`.
4. Add the section to `unremarkable/templates/dashboard.html`. Keep body text pure black, because the panel has 16 greys and no colour.
5. Add sample data to `unremarkable/demo.py`, so `--demo` shows it.
6. Add the module to the tables in README.md and CLAUDE.md.

Ground rules for data sources: they must be **free** for one person refreshing every 30 minutes, work **without a
human in the loop**, and not scrape sites whose terms forbid it. A free API key is fine. Unofficial endpoints are
fine if they're labelled as such. [docs/module-ideas.md](docs/module-ideas.md) lists researched, verified candidates.

## Supporting another reMarkable

See [docs/porting.md](docs/porting.md).

## Tablet code

`device/main.go` builds `unremarkable/bin/tabloid-show-armv7`. After changing it:

```sh
cd device && go test ./... && GOOS=linux GOARCH=arm GOARM=7 CGO_ENABLED=0 \
  go build -trimpath -ldflags "-s -w" -o ../unremarkable/bin/tabloid-show-armv7 .
```

`device/rm2/main.cpp` builds `unremarkable/bin/tabloid-show-rm2-armv7`, the reMarkable 2 version (C++, on top of
the swtcon display driver). After changing it, on Linux or WSL:

```sh
sudo apt install g++-arm-linux-gnueabihf git curl
sh device/rm2/build.sh
```

That binary is GPL-3.0 because of swtcon. See [device/rm2/README.md](device/rm2/README.md).

Anything that runs on the tablet must follow the safety rules in [CLAUDE.md](CLAUDE.md#tablet-safety-rules-do-not-relax).
In short: write only inside `/home/root/tabloid`, and never modify system files or disable the reMarkable app.

## Pull requests

- Include before and after `--demo` screenshots for visual changes.
- Never include `.env`, `config.toml`, calendar links or screenshots of your real dashboard.
- Say which tablet and firmware you tested on (`tabloid tablet info`).
