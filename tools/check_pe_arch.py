#!/usr/bin/env python3
"""Fail unless every given Windows DLL/EXE is a 64-bit x86 (AMD64) binary.

NVDA 2026.1 and later run as a 64-bit process and cannot load 32-bit DLLs.
CI runs this on the built ``mbrola.dll`` and ``espeak-ng-mbrola.dll`` so a
wrong-architecture build can never be packaged.

Usage: python tools/check_pe_arch.py file.dll [file2.dll ...]
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

IMAGE_FILE_MACHINE = {
	0x014C: "x86 (32-bit)",
	0x8664: "x64 (AMD64)",
	0xAA64: "ARM64",
}
REQUIRED_MACHINE = 0x8664


class NotPeFileError(ValueError):
	pass


def pe_machine(data: bytes) -> int:
	"""Return the COFF ``Machine`` field of a PE image."""
	if len(data) < 0x40 or data[:2] != b"MZ":
		raise NotPeFileError("missing MZ header")
	(pe_offset,) = struct.unpack_from("<I", data, 0x3C)
	if len(data) < pe_offset + 6 or data[pe_offset : pe_offset + 4] != b"PE\0\0":
		raise NotPeFileError("missing PE signature")
	(machine,) = struct.unpack_from("<H", data, pe_offset + 4)
	return machine


def check(paths: list[Path]) -> list[str]:
	"""Return one error message per file that is not x64."""
	errors = []
	for path in paths:
		try:
			machine = pe_machine(path.read_bytes()[:4096])
		except (OSError, NotPeFileError) as e:
			errors.append(f"{path}: {e}")
			continue
		if machine != REQUIRED_MACHINE:
			name = IMAGE_FILE_MACHINE.get(machine, hex(machine))
			errors.append(f"{path}: built for {name}, but NVDA needs x64")
		else:
			print(f"{path}: x64 OK")
	return errors


def main(argv: list[str]) -> int:
	if not argv:
		print(__doc__, file=sys.stderr)
		return 2
	errors = check([Path(a) for a in argv])
	for e in errors:
		print(e, file=sys.stderr)
	return 1 if errors else 0


if __name__ == "__main__":
	sys.exit(main(sys.argv[1:]))
