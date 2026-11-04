import io

import pytest
from core.errors import InvalidVoiceFileError
from core.voice_file import parse_header, read_header, read_header_from_path
from voice_fixtures import make_voice_bytes


def test_parses_new_format_header():
	header = parse_header(make_voice_bytes(version=b"2.069", diphones=2025, rate=16000))
	assert header.format_version == "2.069"
	assert header.diphone_count == 2025
	assert header.sample_rate == 16000


def test_parses_old_format_header():
	header = parse_header(make_voice_bytes(new_format=False, rate=22050))
	assert header.sample_rate == 22050


def test_real_world_prefix_of_en1():
	# First 11 bytes of the real en1 database: magic + version.
	data = make_voice_bytes()
	assert data.startswith(b"MBROLA2.060")
	assert parse_header(data).sample_rate == 16000


@pytest.mark.parametrize(
	"data,message",
	[
		(b"", "signature"),
		(b"<html><body>404</body></html>", "signature"),
		(b"PK\x03\x04" + b"\x00" * 60, "signature"),
		(b"MBROLA2.0", "truncated"),
		(make_voice_bytes(version=b"abcde"), "format version"),
		(make_voice_bytes(diphones=0), "no diphones"),
		(make_voice_bytes(rate=12), "sample rate"),
		(make_voice_bytes()[:18], "truncated"),
	],
)
def test_rejects_bad_headers(data, message):
	with pytest.raises(InvalidVoiceFileError, match=message):
		parse_header(data)


def test_read_header_from_stream_reads_only_probe():
	stream = io.BytesIO(make_voice_bytes(payload=b"x" * 10_000))
	read_header(stream)
	assert stream.tell() == 64


def test_read_header_from_missing_path(tmp_path):
	with pytest.raises(InvalidVoiceFileError, match="Could not read"):
		read_header_from_path(tmp_path / "nope")
