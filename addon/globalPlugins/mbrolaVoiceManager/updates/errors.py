"""Why an update check or download failed.

The kind decides what the user is told (``messages.py`` translates it); the
detail is the technical reason, shown after it and written to NVDA's log.
"""

from __future__ import annotations

import enum


class Problem(enum.Enum):
	NETWORK = "network"
	"""GitHub could not be reached, or answered with an error."""
	BAD_RESPONSE = "bad response"
	"""GitHub answered, but not with the release information expected."""
	NO_PACKAGE = "no package"
	"""The newest release has no ``.nvda-addon`` file attached."""
	DOWNLOAD_INCOMPLETE = "download incomplete"
	"""The downloaded file does not have the size GitHub announced."""
	CHECKSUM_MISMATCH = "checksum mismatch"
	"""The downloaded file does not have the SHA-256 GitHub announced."""
	WRONG_PACKAGE = "wrong package"
	"""The file is not this add-on, or not the version that was offered."""


class UpdateError(Exception):
	def __init__(self, problem: Problem, detail: str = ""):
		self.problem = problem
		self.detail = detail
		super().__init__(f"{problem.value}: {detail}" if detail else problem.value)
