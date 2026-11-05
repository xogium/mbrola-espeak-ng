import shutil
import tomllib
import zipfile
from pathlib import PurePosixPath

import build_addon
import pytest
from test_check_pe_arch import make_pe


def test_real_manifest_targets_64_bit_nvda():
	m = build_addon.read_manifest(build_addon.ADDON_DIR)
	assert m["name"] == "mbrolaEspeak"
	assert m["minimumNVDAVersion"] == "2026.1.0"
	assert m["lastTestedNVDAVersion"] == "2026.3.0"
	assert (build_addon.ADDON_DIR / "doc" / "en" / m["docFileName"]).is_file()


def test_real_manifest_author_and_version():
	m = build_addon.read_manifest(build_addon.ADDON_DIR)
	assert m["author"] == "Casey Reeves"
	assert m["version"] == "0.2.0"


def test_pyproject_version_matches_manifest():
	# Two places hold the version; a release must never ship with them out of step.
	text = (build_addon.REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
	pyproject_version = tomllib.loads(text)["project"]["version"]
	assert pyproject_version == build_addon.read_manifest(build_addon.ADDON_DIR)["version"]


@pytest.mark.parametrize(
	"rel,included",
	[
		("manifest.ini", True),
		("synthDrivers/mbrola_espeak/__init__.py", True),
		("synthDrivers/mbrola_espeak/__pycache__/x.cpython-313.pyc", False),
		("synthDrivers/mbrola_espeak/bin/mbrola.dll", True),
		("synthDrivers/mbrola_espeak/bin/libmbrola.so", False),
		("synthDrivers/mbrola_espeak/espeak-ng-data/mbrola/en1", False),
		("synthDrivers/mbrola_espeak/espeak-ng-data/mbrola_ph/en1_phtrans", True),
		("synthDrivers/mbrola_espeak/espeak-ng-data/voices/mb/mb-en1", True),
	],
)
def test_should_include(rel, included):
	assert build_addon.should_include(PurePosixPath(rel)) is included


@pytest.fixture
def addon_copy(tmp_path):
	dest = tmp_path / "addon"
	shutil.copytree(build_addon.ADDON_DIR, dest, ignore=shutil.ignore_patterns("__pycache__", "bin", "espeak-ng-data"))
	return dest


def add_native(addon_dir, machine=0x8664):
	driver = addon_dir / "synthDrivers" / "mbrola_espeak"
	(driver / "bin").mkdir(parents=True)
	(driver / "bin" / "espeak-ng-mbrola.dll").write_bytes(make_pe(machine))
	(driver / "bin" / "mbrola.dll").write_bytes(make_pe(machine))
	data = driver / "espeak-ng-data"
	(data / "voices" / "mb").mkdir(parents=True)
	(data / "voices" / "mb" / "mb-en1").write_text("mbrola en1 en1_phtrans\n")
	(data / "mbrola_ph").mkdir()
	(data / "mbrola_ph" / "en1_phtrans").write_bytes(b"x")
	(data / "phondata").write_bytes(b"x")
	(data / "mbrola").mkdir()
	(data / "mbrola" / "en1").write_bytes(b"a voice that must not be shipped")


def test_refuses_without_native_files(addon_copy, tmp_path):
	with pytest.raises(SystemExit, match="missing"):
		build_addon.build(addon_copy, tmp_path / "dist")


def test_refuses_32_bit_dlls(addon_copy, tmp_path):
	add_native(addon_copy, machine=0x014C)
	with pytest.raises(SystemExit, match="32-bit"):
		build_addon.build(addon_copy, tmp_path / "dist")


def test_builds_package(addon_copy, tmp_path):
	add_native(addon_copy)
	target = build_addon.build(addon_copy, tmp_path / "dist")
	assert target.name == "mbrolaEspeak-0.2.0.nvda-addon"
	names = set(zipfile.ZipFile(target).namelist())
	assert "manifest.ini" in names
	assert "synthDrivers/mbrola_espeak/__init__.py" in names
	assert "synthDrivers/mbrola_espeak/core/engine.py" in names
	assert "globalPlugins/mbrolaVoiceManager/__init__.py" in names
	assert "synthDrivers/mbrola_espeak/bin/mbrola.dll" in names
	assert "synthDrivers/mbrola_espeak/espeak-ng-data/mbrola/en1" not in names
	assert not any("__pycache__" in n for n in names)


def test_allow_missing_native_for_packaging_tests(addon_copy, tmp_path):
	target = build_addon.build(addon_copy, tmp_path / "dist", allow_missing_native=True)
	assert target.is_file()
