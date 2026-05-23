#!/bin/bash
set -e
cd "$(dirname "$(readlink -f "$0")")"

if [ ! -d ".venv" ]; then
    echo "[Pochtalion] Virtual environment not found. Creating..."
    python3 -m venv .venv
    echo "[Pochtalion] Installing dependencies..."
    .venv/bin/pip install -r requirements.txt
fi

exec .venv/bin/python main.py
