"""Shared pytest setup.

Makes ``tools/`` and the add-on's ``core`` package importable without
installing anything. ``core`` is imported as a top-level package so its
NVDA-dependent parent (``synthDrivers/mbrola_espeak/__init__.py``) is never
imported by the core tests.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DRIVER_DIR = REPO_ROOT / "addon" / "synthDrivers" / "mbrola_espeak"

for path in (REPO_ROOT / "tools", DRIVER_DIR):
	if str(path) not in sys.path:
		sys.path.insert(0, str(path))
