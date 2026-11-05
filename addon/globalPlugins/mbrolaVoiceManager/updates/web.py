"""HTTPS requests to GitHub. The only module in this package that touches the network.

Everything else takes these functions as arguments, so tests never go online.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import BinaryIO

from .errors import Problem, UpdateError

TIMEOUT_SECONDS = 20
_API_HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


def _user_agent(addon_version: str) -> str:
	# GitHub refuses API requests without a User-Agent.
	return f"mbrolaEspeak-NVDA-addon/{addon_version}"


def make_json_fetcher(addon_version: str, timeout: float = TIMEOUT_SECONDS):
	"""A ``fetch_json(url) -> object | None`` function. ``None`` means "not found" (HTTP 404)."""

	def fetch_json(url: str) -> object | None:
		headers = {**_API_HEADERS, "User-Agent": _user_agent(addon_version)}
		request = urllib.request.Request(url, headers=headers)
		try:
			with urllib.request.urlopen(request, timeout=timeout) as response:
				body = response.read()
		except urllib.error.HTTPError as e:
			if e.code == 404:
				return None
			raise UpdateError(Problem.NETWORK, f"HTTP {e.code} {e.reason}") from e
		except (urllib.error.URLError, OSError) as e:
			raise UpdateError(Problem.NETWORK, str(getattr(e, "reason", e))) from e
		try:
			return json.loads(body)
		except ValueError as e:
			raise UpdateError(Problem.BAD_RESPONSE, f"not JSON: {e}") from e

	return fetch_json


def make_opener(addon_version: str, timeout: float = TIMEOUT_SECONDS):
	"""An ``open_url(url) -> binary stream`` function for downloads. GitHub's redirects are followed."""

	def open_url(url: str) -> BinaryIO:
		request = urllib.request.Request(url, headers={"User-Agent": _user_agent(addon_version)})
		try:
			response = urllib.request.urlopen(request, timeout=timeout)
		except urllib.error.HTTPError as e:
			raise UpdateError(Problem.NETWORK, f"HTTP {e.code} {e.reason}") from e
		except (urllib.error.URLError, OSError) as e:
			raise UpdateError(Problem.NETWORK, str(getattr(e, "reason", e))) from e
		if not response.geturl().startswith("https://"):
			response.close()
			raise UpdateError(Problem.NETWORK, "the download was redirected away from HTTPS")
		return response

	return open_url
