import os
import shutil

from voice_fixtures import make_voice_bytes

from core.voice_file import parse_header
from core.voice_store import InstalledVoice
from core.voice_sync import link_or_copy, sync_voices

MANAGED = {"en1", "us1", "de6"}


def voice(store_dir, name, payload=b"p"):
	store_dir.mkdir(parents=True, exist_ok=True)
	data = make_voice_bytes(payload=payload)
	path = store_dir / name
	path.write_bytes(data)
	return InstalledVoice(name=name, path=path, header=parse_header(data))


def test_adds_missing_voices(tmp_path):
	v = voice(tmp_path / "store", "en1")
	target = tmp_path / "data" / "mbrola"
	report = sync_voices([v], target, MANAGED)
	assert report.added == ["en1"] and report.ok
	assert (target / "en1").read_bytes() == v.path.read_bytes()


def test_second_sync_is_a_no_op(tmp_path):
	v = voice(tmp_path / "store", "en1")
	target = tmp_path / "t"
	sync_voices([v], target, MANAGED)
	report = sync_voices([v], target, MANAGED)
	assert report.unchanged == ["en1"] and report.added == []


def test_copy_fallback_also_counts_as_current(tmp_path):
	v = voice(tmp_path / "store", "en1")
	target = tmp_path / "t"
	sync_voices([v], target, MANAGED, linker=shutil.copy2)
	assert not os.path.samefile(v.path, target / "en1")
	report = sync_voices([v], target, MANAGED, linker=shutil.copy2)
	assert report.unchanged == ["en1"]


def test_replaced_voice_is_updated(tmp_path):
	store = tmp_path / "store"
	target = tmp_path / "t"
	sync_voices([voice(store, "en1", b"old")], target, MANAGED, linker=shutil.copy2)
	newer = voice(store, "en1", b"newer and longer")
	report = sync_voices([newer], target, MANAGED, linker=shutil.copy2)
	assert report.added == ["en1"]
	assert (target / "en1").read_bytes().endswith(b"newer and longer")


def test_removes_stale_managed_files_only(tmp_path):
	target = tmp_path / "t"
	target.mkdir()
	(target / "us1").write_bytes(b"stale")
	(target / "keep-me.txt").write_text("unmanaged")
	report = sync_voices([], target, MANAGED)
	assert report.removed == ["us1"]
	assert (target / "keep-me.txt").exists()


def test_failures_are_reported_not_raised(tmp_path):
	v = voice(tmp_path / "store", "en1")

	def failing_linker(src, dest):
		raise PermissionError("in use")

	report = sync_voices([v], tmp_path / "t", MANAGED, linker=failing_linker)
	assert not report.ok
	assert "in use" in report.failed["en1"]


def test_link_or_copy_falls_back_to_copy(tmp_path, monkeypatch):
	src = tmp_path / "a"
	src.write_bytes(b"data")

	def no_links(*args):
		raise OSError("cross-device link")

	monkeypatch.setattr(os, "link", no_links)
	link_or_copy(src, tmp_path / "b")
	assert (tmp_path / "b").read_bytes() == b"data"
