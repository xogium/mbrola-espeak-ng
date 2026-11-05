"""Shared pytest setup.

Makes ``tools/`` and the add-on's NVDA-free packages importable without
installing anything. ``core`` and ``updates`` are imported as top-level
packages so their NVDA-dependent parents (``synthDrivers/mbrola_espeak`` and
``globalPlugins/mbrolaVoiceManager``) are never imported by their tests.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DRIVER_DIR = REPO_ROOT / "addon" / "synthDrivers" / "mbrola_espeak"
PLUGIN_DIR = REPO_ROOT / "addon" / "globalPlugins" / "mbrolaVoiceManager"

for path in (REPO_ROOT / "tools", REPO_ROOT / "tests", DRIVER_DIR, PLUGIN_DIR):
	if str(path) not in sys.path:
		sys.path.insert(0, str(path))
