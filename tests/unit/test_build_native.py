import json
import subprocess

import build_native
import pytest


def test_pins_are_full_commit_hashes():
	pins = build_native.load_pins()
	assert set(pins) == {"mbrola", "espeak-ng"}
	for pin in pins.values():
		assert len(pin.commit) == 40 and all(c in "0123456789abcdef" for c in pin.commit)
		assert pin.repo.startswith("https://")


def test_load_pins_skips_comment_keys(tmp_path):
	f = tmp_path / "v.json"
	f.write_text(json.dumps({"_comment": "x", "a": {"repo": "https://r", "ref": "main", "commit": "c" * 40}}))
	assert list(build_native.load_pins(f)) == ["a"]


def test_windows_build_is_64_bit_and_static_crt():
	args = build_native.espeak_cmake_args("windows")
	assert args[:2] == ["-A", "x64"]
	assert "-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded" in args
	assert build_native.mbrola_cmake_args("windows", build_native.REPO_ROOT)[:2] == ["-A", "x64"]


@pytest.mark.parametrize("target", build_native.TARGETS)
def test_espeak_args_enable_mbrola_and_its_data(target):
	args = build_native.espeak_cmake_args(target)
	assert "-DUSE_MBROLA=ON" in args
	# Regression: without HAVE_MBROLA, eSpeak NG silently skips mbrola_ph/*_phtrans.
	assert "-DHAVE_MBROLA=ON" in args
	assert "-DBUILD_SHARED_LIBS=ON" in args
	assert "-DUSE_LIBPCAUDIO=OFF" in args


def test_patch_directories_contain_described_patches():
	for sub in ("mbrola", "espeak-ng"):
		patches = sorted((build_native.NATIVE_DIR / "patches" / sub).glob("*.patch"))
		assert patches, sub
		for p in patches:
			text = p.read_text(encoding="utf-8")
			# Every patch explains itself before the diff starts.
			assert text.index("---") > 200, p.name


def _fake_builds(tmp_path, target):
	mb = tmp_path / "mb" / "Release"
	es = tmp_path / "es"
	mb.mkdir(parents=True)
	(es / "src" / "Release").mkdir(parents=True)
	data = es / "espeak-ng-data"
	(data / "voices" / "mb").mkdir(parents=True)
	(data / "voices" / "mb" / "mb-en1").write_text("mbrola en1 en1_phtrans\n")
	(data / "mbrola").mkdir()
	(data / "mbrola" / "en1").write_bytes(b"MBROLA voice that must not be shipped")
	if target == "windows":
		(mb / "mbrola.dll").write_bytes(b"m")
		(es / "src" / "Release" / "espeak-ng.dll").write_bytes(b"e")
	else:
		(mb / "libmbrola.so").write_bytes(b"m")
		(es / "src" / "libespeak-ng.so.1").write_bytes(b"e")
	return tmp_path / "mb", es


@pytest.mark.parametrize("target", build_native.TARGETS)
def test_stage_outputs_layout_and_no_voices(tmp_path, target):
	mb, es = _fake_builds(tmp_path, target)
	stage = tmp_path / "stage"
	staged = build_native.stage_outputs(target, mb, es, stage)
	assert staged["espeak"].read_bytes() == b"e"
	assert staged["mbrola"].read_bytes() == b"m"
	assert staged["espeak"].parent == stage / "bin"
	assert (stage / "espeak-ng-data" / "voices" / "mb" / "mb-en1").is_file()
	# The mbrola folder exists (eSpeak NG looks there) but is empty.
	assert list((stage / "espeak-ng-data" / "mbrola").iterdir()) == []


def test_stage_outputs_replaces_old_data(tmp_path):
	mb, es = _fake_builds(tmp_path, "windows")
	stage = tmp_path / "stage"
	(stage / "espeak-ng-data").mkdir(parents=True)
	(stage / "espeak-ng-data" / "stale").write_text("old")
	build_native.stage_outputs("windows", mb, es, stage)
	assert not (stage / "espeak-ng-data" / "stale").exists()


def test_find_one_reports_missing(tmp_path):
	with pytest.raises(FileNotFoundError):
		build_native.find_one(tmp_path, ["nothing.dll"])


def test_apply_patches_in_order(tmp_path):
	repo = tmp_path / "repo"
	repo.mkdir()
	subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
	(repo / "f.txt").write_text("a\n")
	patches = tmp_path / "patches"
	patches.mkdir()
	(patches / "0002-second.patch").write_text(
		"--- a/f.txt\n+++ b/f.txt\n@@ -1 +1 @@\n-b\n+c\n",
	)
	(patches / "0001-first.patch").write_text(
		"--- a/f.txt\n+++ b/f.txt\n@@ -1 +1 @@\n-a\n+b\n",
	)
	applied = build_native.apply_patches(repo, patches)
	assert [p.name for p in applied] == ["0001-first.patch", "0002-second.patch"]
	assert (repo / "f.txt").read_text() == "c\n"


def test_harness_wrapper_replaces_mbrowrap(tmp_path):
	target = tmp_path / "src" / "libespeak-ng"
	target.mkdir(parents=True)
	(target / "mbrowrap.c").write_text("upstream")
	build_native.install_linux_harness_wrapper(tmp_path)
	assert "dlopen" in (target / "mbrowrap.c").read_text()


def test_fetch_disables_crlf_conversion(tmp_path, monkeypatch):
	"""Regression: on Windows CI, core.autocrlf=true made upstream sources CRLF and our patches failed."""
	calls = []
	monkeypatch.setattr(build_native, "run", lambda cmd, cwd=None: calls.append(cmd))
	pin = build_native.SourcePin("x", "https://example.invalid/x.git", "main", "a" * 40)
	monkeypatch.setattr(build_native, "git_output", lambda args, cwd: pin.commit)
	build_native.fetch_source(pin, tmp_path / "x")
	assert ["git", "config", "core.autocrlf", "false"] in calls
	assert calls.index(["git", "config", "core.autocrlf", "false"]) < next(
		i for i, c in enumerate(calls) if c[:2] == ["git", "checkout"]
	)


def test_patches_are_kept_byte_exact_by_gitattributes():
	attributes = (build_native.REPO_ROOT / ".gitattributes").read_text()
	assert "*.patch -text" in attributes
	for patch in (build_native.NATIVE_DIR / "patches").rglob("*.patch"):
		assert b"\r\n" not in patch.read_bytes(), patch.name
