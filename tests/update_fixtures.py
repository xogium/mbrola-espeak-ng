"""Fake add-on packages and GitHub release answers for the update tests."""

from __future__ import annotations

import hashlib
import io
import zipfile

REPOSITORY = "xogium/mbrola-espeak-ng"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"


def make_package(name: str = "mbrolaEspeak", version: str = "0.3.0") -> bytes:
	"""A minimal ``.nvda-addon``: a zip with a manifest."""
	buffer = io.BytesIO()
	with zipfile.ZipFile(buffer, "w") as z:
		z.writestr("manifest.ini", f'name = {name}\nversion = {version}\nsummary = "x"\n')
		z.writestr("globalPlugins/mbrolaVoiceManager/__init__.py", "")
	return buffer.getvalue()


def release_json(
	tag: str = "v0.3.0",
	package: bytes | None = None,
	asset_name: str | None = None,
	digest: str | None = "auto",
	url: str | None = None,
	extra_assets: list | None = None,
) -> dict:
	"""What ``GET /repos/{owner}/{repo}/releases/latest`` returns, trimmed to the fields used."""
	package = make_package(version=tag.removeprefix("v")) if package is None else package
	asset_name = asset_name or f"mbrolaEspeak-{tag.removeprefix('v')}.nvda-addon"
	if digest == "auto":
		digest = "sha256:" + hashlib.sha256(package).hexdigest()
	return {
		"tag_name": tag,
		"html_url": f"https://github.com/{REPOSITORY}/releases/tag/{tag}",
		"draft": False,
		"prerelease": False,
		"assets": [
			*(extra_assets or []),
			{
				"name": asset_name,
				"size": len(package),
				"digest": digest,
				"browser_download_url": url or f"https://github.com/{REPOSITORY}/releases/download/{tag}/{asset_name}",
			},
		],
	}


class FakeGitHub:
	"""Answers ``fetch_json`` and ``open_url`` from memory, and records what was asked."""

	def __init__(self, release: dict | None = None, package: bytes | None = None):
		self.release = release
		self.package = package
		self.fetched: list[str] = []
		self.opened: list[str] = []

	def fetch_json(self, url: str):
		self.fetched.append(url)
		return self.release

	def open_url(self, url: str):
		self.opened.append(url)
		return io.BytesIO(self.package)
