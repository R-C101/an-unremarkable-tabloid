#!/bin/sh
# rmdash installer for macOS and Linux. Run from the rmdash folder:  sh install.sh
# Installs uv (which brings its own Python) if needed, installs rmdash's
# dependencies, then starts the setup wizard. Safe to run again at any time.
set -e
cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv, a small tool that installs Python and rmdash's dependencies..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  export PATH
fi

echo "Installing rmdash's dependencies..."
uv sync --quiet
echo "Downloading the headless browser used to draw the dashboard (once, about 150 MB)..."
uv run --quiet playwright install chromium

uv run rmdash setup "$@"
echo
echo "Next time, run commands from this folder like:  uv run rmdash setup"
