"""Pytest setup: put both server/ and prototype/ on sys.path."""

from __future__ import annotations

import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
PROTOTYPE_DIR = SERVER_DIR.parent / "prototype"
sys.path.insert(0, str(SERVER_DIR))
sys.path.insert(0, str(PROTOTYPE_DIR))
