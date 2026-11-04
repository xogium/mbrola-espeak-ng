import zipfile

import pytest
from voice_fixtures import make_voice_bytes

from core import voice_store
from core.errors import InvalidVoiceFileError, UnknownVoiceNameError, VoiceArchiveError
from core.voice_store import VoiceStore, resolve_database_name

KNOWN = {"en1", "us1", "de6", "fr1"}


@pytest.fixture
def store(tmp_path):
	return VoiceStore(tmp_path / "store", KNOWN)


def leftovers(store):
	return [p.name for p in store.root.iterdir() if p.name.endswith(".partial")] if store.root.exists() else []


@pytest.mark.parametrize(
	"file_name,expected",
	[
		("en1", "en1"),
		("EN1", "en1"),
		("en1.dat", "en1"),
		("data/en1/en1", "en1"),
		("C:\\Users\\me\\Downloads\\us1", "us1"),
		("en1-980910.zip", None),
		("en2", None),
		("../../../etc/passwd", None),
		("", None),
	],
)
def test_resolve_database_name(file_name, expected):
	assert resolve_database_name(file_name, KNOWN) == expected


def test_import_single_file(store, tmp_path):
	src = tmp_path / "en1"
	src.write_bytes(make_voice_bytes(rate=16000))
	[voice] = store.import_path(src)
	assert voice.name == "en1"
	assert voice.header.sample_rate == 16000
	assert (store.root / "en1").read_bytes() == src.read_bytes()
	assert store.installed_names() == {"en1"}
	assert leftovers(store) == []


def test_import_with_name_override(store, tmp_path):
	src = tmp_path / "downloaded-voice.bin"
	src.write_bytes(make_voice_bytes())
	[voice] = store.import_path(src, name="de6")
	assert voice.name == "de6"


def test_import_rejects_unknown_name(store, tmp_path):
	src = tmp_path / "mystery"
	src.write_bytes(make_voice_bytes())
	with pytest.raises(UnknownVoiceNameError, match="original file name"):
		store.import_path(src)
	with pytest.raises(UnknownVoiceNameError):
		store.import_path(src, name="zz9")
	assert not store.root.exists()


def test_import_rejects_invalid_file_and_writes_nothing(store, tmp_path):
	src = tmp_path / "en1"
	src.write_bytes(b"<html>not found</html>")
	with pytest.raises(InvalidVoiceFileError):
		store.import_path(src)
	assert not (store.root / "en1").exists()


def test_failed_import_keeps_existing_voice(store, tmp_path, monkeypatch):
	good = tmp_path / "en1"
	good.write_bytes(make_voice_bytes(payload=b"old"))
	store.import_path(good)

	def boom(*args, **kwargs):
		raise OSError("disk full")

	monkeypatch.setattr(voice_store.os, "replace", boom)
	newer = tmp_path / "sub"
	newer.mkdir()
	(newer / "en1").write_bytes(make_voice_bytes(payload=b"new"))
	with pytest.raises(InvalidVoiceFileError, match="disk full"):
		store.import_path(newer / "en1")
	assert (store.root / "en1").read_bytes().endswith(b"old")
	assert leftovers(store) == []


def make_zip(path, members):
	with zipfile.ZipFile(path, "w") as z:
		for name, data in members.items():
			z.writestr(name, data)
	return path


def test_import_zip_with_several_voices_and_junk(store, tmp_path):
	archive = make_zip(
		tmp_path / "MBROLA-voices-master.zip",
		{
			"MBROLA-voices-master/data/en1/en1": make_voice_bytes(rate=16000),
			"MBROLA-voices-master/data/en1/README.txt": b"readme",
			"MBROLA-voices-master/data/us1/us1": make_voice_bytes(rate=16000),
			"MBROLA-voices-master/data/us1/license.txt": b"licence",
			"MBROLA-voices-master/data/fr1/fr1": b"not really a voice",
			"MBROLA-voices-master/data/xx9/xx9": make_voice_bytes(),
		},
	)
	imported = store.import_path(archive)
	assert sorted(v.name for v in imported) == ["en1", "us1"]
	assert sorted(p.name for p in store.root.iterdir()) == ["en1", "us1"]


def test_zip_slip_names_stay_inside_store(store, tmp_path):
	archive = make_zip(tmp_path / "evil.zip", {"../../outside/en1": make_voice_bytes()})
	store.import_path(archive)
	assert (store.root / "en1").is_file()
	assert not (tmp_path / "outside").exists()


def test_zip_without_voices(store, tmp_path):
	archive = make_zip(tmp_path / "empty.zip", {"readme.txt": b"hello"})
	with pytest.raises(VoiceArchiveError, match="does not contain"):
		store.import_path(archive)


def test_oversized_zip_member_is_skipped(store, tmp_path, monkeypatch):
	monkeypatch.setattr(voice_store, "MAX_VOICE_BYTES", 100)
	archive = make_zip(tmp_path / "big.zip", {"en1": make_voice_bytes(payload=b"x" * 500)})
	with pytest.raises(VoiceArchiveError):
		store.import_path(archive)
	assert leftovers(store) == []


def test_installed_ignores_unknown_and_invalid_files(store):
	store.root.mkdir(parents=True)
	(store.root / "en1").write_bytes(make_voice_bytes())
	(store.root / "us1").write_bytes(b"garbage")
	(store.root / "notes.txt").write_text("x")
	(store.root / "de6").mkdir()
	assert [v.name for v in store.installed()] == ["en1"]


def test_installed_on_missing_store(store):
	assert store.installed() == []


def test_remove(store, tmp_path):
	src = tmp_path / "en1"
	src.write_bytes(make_voice_bytes())
	store.import_path(src)
	store.remove("en1")
	assert store.installed() == []
	store.remove("en1")  # removing twice is fine
	with pytest.raises(UnknownVoiceNameError):
		store.remove("../escape")
