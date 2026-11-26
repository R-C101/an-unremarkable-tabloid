#!/bin/sh
# tabloid installer for macOS and Linux. Run from the tabloid folder:  sh install.sh
# Installs uv (which brings its own Python) if needed, installs tabloid's
# dependencies, then starts the setup wizard. Safe to run again at any time.
set -e
cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv, a small tool that installs Python and tabloid's dependencies..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  export PATH
fi

echo "Installing tabloid's dependencies..."
uv sync --quiet
echo "Downloading the headless browser used to draw the dashboard (once, about 150 MB)..."
uv run --quiet playwright install chromium

uv run tabloid setup "$@"
echo
echo "Next time, run commands from this folder like:  uv run tabloid setup"
