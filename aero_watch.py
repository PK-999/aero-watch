#!/usr/bin/env python3
"""Compatibility launcher. Originally by Pankaj Tanwar; enhanced by Puneeth Kakarla."""

import sys
from importlib.util import find_spec
from pathlib import Path

if find_spec("aerowatch") is None:
    sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from aerowatch.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
