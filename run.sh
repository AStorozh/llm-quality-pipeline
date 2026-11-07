#!/usr/bin/env bash
# One-command launcher for macOS / Linux.
# On first run it creates a local virtual environment and installs the
# optional dependencies; when requirements.txt changes it installs them
# again; otherwise it just starts the app.
set -e
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
STAMP=.venv/requirements.installed

if [ ! -d .venv ]; then
  echo "First run: preparing the environment..."
  "$PY" -m venv .venv
  ./.venv/bin/python -m pip install --quiet --upgrade pip
fi

if ! cmp -s requirements.txt "$STAMP"; then
  echo "Installing dependencies..."
  ./.venv/bin/python -m pip install --quiet -r requirements.txt
  cp requirements.txt "$STAMP"
fi

exec ./.venv/bin/python main.py
