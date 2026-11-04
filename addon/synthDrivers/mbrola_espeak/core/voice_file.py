"""Reading and checking the header of an MBROLA voice database.

The layout below matches ``Database/database.c`` (``init_DatabaseBasic``) in
the MBROLA sources. All numbers are little-endian::

    offset  size  field
    0       6     magic "MBROLA"
    6       5     format version, e.g. "2.060"
    11      2     int16  number of diphones
    13      2     uint16 old-format mark size (0 means "new format")
    15      4     int32  mark size            (new format only)
    ..      4     int32  raw sample size
    ..      2     int16  sample rate in Hz

We only read this header. That is enough to reject files that are not voices
(wrong download, HTML error pages, a zip that was not extracted) before they
are copied, and to show the sample rate in the UI.
"""

from __future__ import annotations

import dataclasses
import re
import struct
from pathlib import Path
from typing import BinaryIO

from .errors import InvalidVoiceFileError

MAGIC = b"MBROLA"
HEADER_PROBE_SIZE = 64
_VERSION_RE = re.compile(rb"^\d\.\d{3}$")
# Plausible range for diphone databases; real voices are 8000-22050 Hz.
_MIN_RATE, _MAX_RATE = 4000, 48000


@dataclasses.dataclass(frozen=True)
class MbrolaVoiceHeader:
	format_version: str
	diphone_count: int
	sample_rate: int


def parse_header(data: bytes) -> MbrolaVoiceHeader:
	"""Parse the first bytes of a voice database. Raises :class:`InvalidVoiceFileError`."""
	if len(data) < 6 or not data.startswith(MAGIC):
		raise InvalidVoiceFileError("This is not an MBROLA voice file (the MBROLA signature is missing).")
	if len(data) < 17:
		raise InvalidVoiceFileError("The MBROLA voice file is truncated.")
	version = data[6:11]
	if not _VERSION_RE.match(version):
		raise InvalidVoiceFileError("The MBROLA voice file has an unreadable format version.")
	(diphones,) = struct.unpack_from("<h", data, 11)
	(old_mark_size,) = struct.unpack_from("<H", data, 13)
	offset = 15
	if old_mark_size == 0:
		offset += 4  # new format: an int32 mark size follows
	offset += 4  # int32 raw size
	if len(data) < offset + 2:
		raise InvalidVoiceFileError("The MBROLA voice file is truncated.")
	(rate,) = struct.unpack_from("<h", data, offset)
	if diphones <= 0:
		raise InvalidVoiceFileError("The MBROLA voice file contains no diphones.")
	if not _MIN_RATE <= rate <= _MAX_RATE:
		raise InvalidVoiceFileError(f"The MBROLA voice file has an implausible sample rate ({rate} Hz).")
	return MbrolaVoiceHeader(format_version=version.decode("ascii"), diphone_count=diphones, sample_rate=rate)


def read_header(stream: BinaryIO) -> MbrolaVoiceHeader:
	return parse_header(stream.read(HEADER_PROBE_SIZE))


def read_header_from_path(path: Path) -> MbrolaVoiceHeader:
	try:
		with open(path, "rb") as f:
			return read_header(f)
	except OSError as e:
		raise InvalidVoiceFileError(f"Could not read {path.name}: {e.strerror or e}") from e
