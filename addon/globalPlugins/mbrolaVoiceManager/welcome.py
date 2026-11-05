"""First-run offer to get voices, without any wx code.

After the add-on is installed and NVDA restarts, the user is told once that
no MBROLA voices are installed and offered the download page. "Once" is
remembered by a marker file in the voice store folder, so it survives add-on
updates and never nags. If voices are already installed (for example after
an update), nothing is shown.
"""

from __future__ import annotations

from pathlib import Path

MARKER_NAME = ".welcomeShown"


def marker_path(voice_store_dir: Path) -> Path:
	return Path(voice_store_dir) / MARKER_NAME


def should_offer_voices(installed_voice_count: int, voice_store_dir: Path) -> bool:
	return installed_voice_count == 0 and not marker_path(voice_store_dir).exists()


def remember_offered(voice_store_dir: Path) -> None:
	"""Record that the offer was made. Done *before* showing it, so a crash cannot cause repeats."""
	path = marker_path(voice_store_dir)
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text("The MBROLA add-on showed its first-run message.\n", encoding="utf-8")
