#!/usr/bin/env python3
"""Package the ``addon/`` folder as an ``.nvda-addon`` file.

An NVDA add-on is a zip file with ``manifest.ini`` at its root. This script:

* reads name and version from ``addon/manifest.ini``;
* refuses to build unless the native files from ``tools/build_native.py
  --target windows`` are present and x64 (``--allow-missing-native`` skips this,
  for testing packaging only);
* leaves out caches, any MBROLA voice that may have ended up in
  ``espeak-ng-data/mbrola``, and Linux-only harness files;
* compiles each ``locale/<lang>/LC_MESSAGES/nvda.po`` into the ``nvda.mo``
  NVDA loads (see ``tools/i18n.py``), and ships only the ``.mo``.

Usage: python tools/build_addon.py [--output-dir dist] [--allow-missing-native]
"""

from __future__ import annotations

import argparse
import configparser
import sys
import zipfile
from pathlib import Path, PurePosixPath

import check_pe_arch
import i18n

REPO_ROOT = Path(__file__).resolve().parent.parent
ADDON_DIR = REPO_ROOT / "addon"
DRIVER_REL = PurePosixPath("synthDrivers/mbrola_espeak")
REQUIRED_NATIVE = (
	DRIVER_REL / "bin" / "espeak-ng-mbrola.dll",
	DRIVER_REL / "bin" / "mbrola.dll",
	DRIVER_REL / "espeak-ng-data" / "phondata",
	DRIVER_REL / "espeak-ng-data" / "voices" / "mb" / "mb-en1",
	DRIVER_REL / "espeak-ng-data" / "mbrola_ph" / "en1_phtrans",
)


def read_manifest(addon_dir: Path) -> dict[str, str]:
	text = (addon_dir / "manifest.ini").read_text(encoding="utf-8")
	parser = configparser.ConfigParser(interpolation=None)
	parser.optionxform = str  # keep NVDA's camelCase keys
	parser.read_string("[addon]\n" + text)
	return {k: v.strip().strip('"') for k, v in parser["addon"].items()}


def should_include(rel: PurePosixPath) -> bool:
	parts = rel.parts
	if "__pycache__" in parts or rel.suffix in {".pyc", ".pyo"}:
		return False
	if rel.suffix == ".so":
		return False  # Linux test-harness libraries
	if rel.suffix in {".po", ".pot"}:
		return False  # translation sources; compiled_translations() adds the .mo files
	excluded_dirs = (
		DRIVER_REL / "espeak-ng-data" / "mbrola",  # never ship MBROLA voices
		DRIVER_REL / "espeak-ng-data" / "voices" / "!v",  # eSpeak NG variants (Alex, Michael, ...): unused
	)
	for excluded in excluded_dirs:
		n = len(excluded.parts)
		if len(parts) > n and PurePosixPath(*parts[:n]) == excluded:
			return False
	return True


def collect_files(addon_dir: Path) -> list[tuple[Path, PurePosixPath]]:
	files = []
	for path in sorted(addon_dir.rglob("*")):
		if not path.is_file():
			continue
		rel = PurePosixPath(path.relative_to(addon_dir).as_posix())
		if should_include(rel):
			files.append((path, rel))
	return files


def compiled_translations(addon_dir: Path) -> list[tuple[PurePosixPath, bytes]]:
	"""``(path in the package, .mo bytes)`` for every translation. Raises :class:`i18n.I18nError` if one is broken."""
	compiled = []
	for po in i18n.po_files(addon_dir).values():
		rel = PurePosixPath(po.relative_to(addon_dir).as_posix()).with_suffix(".mo")
		compiled.append((rel, i18n.compile_po_file(po)))
	return compiled


def check_native(addon_dir: Path) -> list[str]:
	errors = [f"missing {rel}" for rel in REQUIRED_NATIVE if not (addon_dir / rel).is_file()]
	dlls = [addon_dir / rel for rel in REQUIRED_NATIVE if rel.suffix == ".dll" and (addon_dir / rel).is_file()]
	errors += check_pe_arch.check(dlls)
	return errors


def build(addon_dir: Path, output_dir: Path, allow_missing_native: bool = False) -> Path:
	manifest = read_manifest(addon_dir)
	if not allow_missing_native:
		errors = check_native(addon_dir)
		if errors:
			raise SystemExit(
				"Native files are missing or wrong; run tools/build_native.py --target windows first:\n  "
				+ "\n  ".join(errors),
			)
	try:
		translations = compiled_translations(addon_dir)
	except i18n.I18nError as e:
		raise SystemExit(f"A translation is broken; fix it or run tools/i18n.py check:\n{e}") from e
	output_dir.mkdir(parents=True, exist_ok=True)
	target = output_dir / f"{manifest['name']}-{manifest['version']}.nvda-addon"
	with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as z:
		for path, rel in collect_files(addon_dir):
			z.write(path, str(rel))
		for rel, data in translations:
			z.writestr(str(rel), data)
	return target


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
	parser.add_argument("--addon-dir", type=Path, default=ADDON_DIR)
	parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / "dist")
	parser.add_argument("--allow-missing-native", action="store_true")
	args = parser.parse_args(argv)
	print(build(args.addon_dir, args.output_dir, args.allow_missing_native))
	return 0


if __name__ == "__main__":
	sys.exit(main())
