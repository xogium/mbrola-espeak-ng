#!/usr/bin/env python3
"""Refuse to publish a release whose tag and add-on package disagree.

The add-on's updater offers a release by its tag (``v0.3.0``) and then checks
that the downloaded package's manifest says the same version. A mismatch
would make every user's update fail, so CI runs this before publishing.

Usage: python tools/check_release.py TAG PACKAGE.nvda-addon
"""

from __future__ import annotations

import argparse
import configparser
import re
import sys
import zipfile
from pathlib import Path

_TAG_RE = re.compile(r"^v(\d+\.\d+\.\d+)$")


def package_manifest(package: Path) -> dict[str, str]:
	with zipfile.ZipFile(package) as z:
		text = z.read("manifest.ini").decode("utf-8")
	parser = configparser.ConfigParser(interpolation=None)
	parser.optionxform = str
	parser.read_string("[addon]\n" + text)
	return {k: v.strip().strip('"') for k, v in parser["addon"].items()}


def check(tag: str, package: Path) -> list[str]:
	"""Problems that must stop the release; empty if it may be published."""
	match = _TAG_RE.match(tag)
	if match is None:
		return [f"tag {tag!r} is not of the form v1.2.3"]
	version = match.group(1)
	try:
		manifest = package_manifest(package)
	except (OSError, zipfile.BadZipFile, KeyError, configparser.Error) as e:
		return [f"{package.name} is not a readable add-on package: {e}"]
	errors = []
	if manifest.get("version") != version:
		errors.append(f"tag {tag} but the package manifest says version {manifest.get('version')!r}")
	expected_name = f"{manifest.get('name')}-{version}.nvda-addon"
	if package.name != expected_name:
		errors.append(f"package file is {package.name}, expected {expected_name}")
	return errors


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
	parser.add_argument("tag")
	parser.add_argument("package", type=Path)
	args = parser.parse_args(argv)
	errors = check(args.tag, args.package)
	for error in errors:
		print(error, file=sys.stderr)
	return 1 if errors else 0


if __name__ == "__main__":
	sys.exit(main())
