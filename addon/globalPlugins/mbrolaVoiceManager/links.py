"""Where to get MBROLA voices, and opening that page in the user's browser."""

from __future__ import annotations

import webbrowser
from collections.abc import Callable

# The MBROLA project's official voice collection: one folder per voice
# (en1, us1, fr1, ...). Each folder holds the voice file and its licence.
VOICES_DOWNLOAD_URL = "https://github.com/numediart/MBROLA-voices/tree/master/data"


def open_voices_page(opener: Callable[[str], object] = webbrowser.open) -> bool:
	"""Open the download page in the default browser. Returns False if that failed."""
	try:
		return bool(opener(VOICES_DOWNLOAD_URL))
	except Exception:
		return False
