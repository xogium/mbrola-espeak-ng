"""Download the package of a :class:`~releases.Release` and prove it is the add-on that was offered.

Checks, in order: the URL is one of the repository's own release downloads;
the size is exactly what GitHub announced; the SHA-256 matches GitHub's
digest when there is one; and the file is an NVDA add-on whose manifest has
this add-on's name and the offered version. Nothing is handed to NVDA's
installer unless all of them pass. The file is written under a temporary
name and renamed only when complete.
"""

from __future__ import annotations

import configparser
import hashlib
import os
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

from .errors import Problem, UpdateError
from .releases import REPOSITORY, Release, download_url_prefix
from .version import parse_version

# A real package is around 20 MB. This only stops a broken or hostile answer from filling the disk.
MAX_PACKAGE_BYTES = 200 * 1024 * 1024
_CHUNK = 256 * 1024

OpenUrl = Callable[[str], BinaryIO]


def read_bundle_manifest(path: Path) -> dict[str, str]:
	"""``name`` and ``version`` (and the rest) from the ``manifest.ini`` inside an ``.nvda-addon``."""
	try:
		with zipfile.ZipFile(path) as bundle:
			text = bundle.read("manifest.ini").decode("utf-8")
		parser = configparser.ConfigParser(interpolation=None)
		parser.optionxform = str
		parser.read_string("[addon]\n" + text)
	except (zipfile.BadZipFile, KeyError, UnicodeDecodeError, configparser.Error, OSError) as e:
		raise UpdateError(Problem.WRONG_PACKAGE, f"not an NVDA add-on package: {e}") from e
	return {k: v.strip().strip('"') for k, v in parser["addon"].items()}


def check_bundle(path: Path, addon_name: str, version: str) -> None:
	manifest = read_bundle_manifest(path)
	if manifest.get("name") != addon_name:
		raise UpdateError(Problem.WRONG_PACKAGE, f"the package is the add-on {manifest.get('name')!r}")
	found = manifest.get("version", "")
	if parse_version(found) is None or parse_version(found) != parse_version(version):
		raise UpdateError(Problem.WRONG_PACKAGE, f"the package is version {found!r}, not {version}")


def _copy(stream: BinaryIO, out: BinaryIO, expected_size: int) -> str:
	"""Copy at most ``expected_size`` bytes and return their SHA-256."""
	digest = hashlib.sha256()
	written = 0
	try:
		while chunk := stream.read(_CHUNK):
			written += len(chunk)
			if written > expected_size:
				raise UpdateError(Problem.DOWNLOAD_INCOMPLETE, f"more than the announced {expected_size} bytes")
			digest.update(chunk)
			out.write(chunk)
	except OSError as e:
		raise UpdateError(Problem.NETWORK, str(e)) from e
	if written != expected_size:
		raise UpdateError(Problem.DOWNLOAD_INCOMPLETE, f"{written} of {expected_size} bytes")
	return digest.hexdigest()


def download_package(
	release: Release,
	dest_dir: Path,
	open_url: OpenUrl,
	addon_name: str,
	repository: str = REPOSITORY,
) -> Path:
	"""Download and check the package. Returns its path in ``dest_dir``. Raises :class:`UpdateError`."""
	if not release.package_url.startswith(download_url_prefix(repository)):
		raise UpdateError(Problem.WRONG_PACKAGE, f"unexpected download address {release.package_url}")
	if release.package_size > MAX_PACKAGE_BYTES:
		raise UpdateError(Problem.WRONG_PACKAGE, f"the package is unreasonably large ({release.package_size} bytes)")
	dest_dir = Path(dest_dir)
	dest_dir.mkdir(parents=True, exist_ok=True)
	# Never trust the asset name as a path.
	dest = dest_dir / f"{addon_name}-{release.version}.nvda-addon"
	fd, tmp_name = tempfile.mkstemp(prefix=f".{addon_name}-", suffix=".partial", dir=dest_dir)
	tmp = Path(tmp_name)
	try:
		with os.fdopen(fd, "wb") as out, open_url(release.package_url) as stream:
			sha256 = _copy(stream, out, release.package_size)
		if release.package_sha256 is not None and sha256 != release.package_sha256:
			raise UpdateError(Problem.CHECKSUM_MISMATCH, f"got {sha256}, GitHub announced {release.package_sha256}")
		check_bundle(tmp, addon_name, release.version)
		os.replace(tmp, dest)
	except BaseException:
		tmp.unlink(missing_ok=True)
		raise
	return dest
