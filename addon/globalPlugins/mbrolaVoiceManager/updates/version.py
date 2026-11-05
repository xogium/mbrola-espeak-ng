"""Add-on version numbers: ``"0.2.0"`` in the manifest, ``"v0.2.0"`` as a release tag."""

from __future__ import annotations

import re

_VERSION_RE = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?$")


def parse_version(text: str) -> tuple[int, int, int] | None:
	"""``"v0.2.0"``, ``"0.2.0"`` or ``"0.2"`` -> ``(0, 2, 0)``.

	Returns ``None`` for anything else, including pre-release suffixes such as
	``"0.3.0-beta1"``: those are never offered as updates.
	"""
	match = _VERSION_RE.match(text.strip())
	if match is None:
		return None
	major, minor, patch = (int(part) if part else 0 for part in match.groups())
	return major, minor, patch


def is_newer(candidate: str, current: str) -> bool:
	"""True if ``candidate`` is a later release than ``current``.

	False whenever either cannot be read: a development build such as
	``"0.3.0-dev"`` must not be "updated" to an older release.
	"""
	new, old = parse_version(candidate), parse_version(current)
	return new is not None and old is not None and new > old
