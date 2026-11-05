"""Find out whether GitHub has a newer release of the add-on.

Releases are published by CI (``.github/workflows/ci.yml``) when a tag such
as ``v0.3.0`` is pushed; the ``.nvda-addon`` package is attached to it.
GitHub's "latest release" is the newest one that is neither a draft nor a
pre-release, so test builds are never offered.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable

from .errors import Problem, UpdateError
from .version import is_newer, parse_version

REPOSITORY = "xogium/mbrola-espeak-ng"
PACKAGE_SUFFIX = ".nvda-addon"
_SHA256_RE = re.compile(r"^sha256:([0-9a-f]{64})$")

FetchJson = Callable[[str], object]


def latest_release_url(repository: str = REPOSITORY) -> str:
	return f"https://api.github.com/repos/{repository}/releases/latest"


def download_url_prefix(repository: str = REPOSITORY) -> str:
	"""Every package URL offered must start with this: the repository's own release downloads."""
	return f"https://github.com/{repository}/releases/download/"


@dataclasses.dataclass(frozen=True)
class Release:
	version: str
	"""Version from the tag, without the leading ``v``: ``"0.3.0"``."""
	page_url: str
	"""The release page on GitHub (release notes)."""
	package_name: str
	package_url: str
	package_size: int
	package_sha256: str | None
	"""Lower-case hex digest, when GitHub provides one (it does for files uploaded since mid-2025)."""


def _pick_package(assets: list, addon_name: str, repository: str) -> dict | None:
	"""The ``.nvda-addon`` asset, preferring ``<addon name>-<version>.nvda-addon`` if there are several."""
	packages = [
		a
		for a in assets
		if isinstance(a, dict)
		and str(a.get("name", "")).endswith(PACKAGE_SUFFIX)
		and str(a.get("browser_download_url", "")).startswith(download_url_prefix(repository))
	]
	named = [a for a in packages if str(a["name"]).startswith(f"{addon_name}-")]
	return (named or packages or [None])[0]


def parse_release(data: object, addon_name: str, repository: str = REPOSITORY) -> Release:
	"""Turn GitHub's JSON for one release into a :class:`Release`. Raises :class:`UpdateError`."""
	if not isinstance(data, dict) or not isinstance(data.get("tag_name"), str):
		raise UpdateError(Problem.BAD_RESPONSE, "no tag_name in the release information")
	tag = data["tag_name"]
	if parse_version(tag) is None:
		raise UpdateError(Problem.BAD_RESPONSE, f"the release tag {tag!r} is not a version number")
	asset = _pick_package(data.get("assets") or [], addon_name, repository)
	if asset is None:
		raise UpdateError(Problem.NO_PACKAGE, f"release {tag} has no {PACKAGE_SUFFIX} file")
	size = asset.get("size")
	if not isinstance(size, int) or size <= 0:
		raise UpdateError(Problem.BAD_RESPONSE, f"{asset['name']} has no size")
	digest = asset.get("digest")
	match = _SHA256_RE.match(digest) if isinstance(digest, str) else None
	return Release(
		version=tag.removeprefix("v"),
		page_url=str(data.get("html_url") or ""),
		package_name=str(asset["name"]),
		package_url=str(asset["browser_download_url"]),
		package_size=size,
		package_sha256=match.group(1) if match else None,
	)


def find_update(
	fetch_json: FetchJson,
	current_version: str,
	addon_name: str,
	repository: str = REPOSITORY,
) -> Release | None:
	"""The latest release if it is newer than ``current_version``; ``None`` if there is nothing newer.

	:param fetch_json: ``url -> parsed JSON``, or ``None`` when GitHub answers 404
		(a repository with no release yet). See ``web.make_json_fetcher``.
	:raises UpdateError:
	"""
	data = fetch_json(latest_release_url(repository))
	if data is None:
		return None
	tag = data.get("tag_name") if isinstance(data, dict) else None
	if isinstance(tag, str) and not is_newer(tag, current_version):
		# Nothing newer (or a tag that is not a version): its assets do not matter.
		return None
	return parse_release(data, addon_name, repository)
