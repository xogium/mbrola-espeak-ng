"""Builders for fake MBROLA voices and eSpeak NG voice definitions used by unit tests."""

from __future__ import annotations

import struct
from pathlib import Path


def make_voice_bytes(
	version: bytes = b"2.060",
	diphones: int = 2116,
	rate: int = 16000,
	new_format: bool = True,
	payload: bytes = b"\x00" * 128,
) -> bytes:
	header = b"MBROLA" + version + struct.pack("<h", diphones)
	if new_format:
		header += struct.pack("<H", 0) + struct.pack("<i", 1234)
	else:
		header += struct.pack("<H", 1234)
	header += struct.pack("<i", 99999) + struct.pack("<h", rate)
	return header + payload


def write_definitions(directory: Path, definitions: dict[str, str]) -> Path:
	"""Write eSpeak NG voice definition files, e.g. {"mb-en1": "en1"} -> mbrola en1 en1_phtrans."""
	directory.mkdir(parents=True, exist_ok=True)
	for identifier, database in definitions.items():
		(directory / identifier).write_text(
			f"name {identifier}-name\nlanguage xx 2\ngender male\nmbrola {database} {database}_phtrans\n",
			encoding="utf-8",
		)
	return directory
