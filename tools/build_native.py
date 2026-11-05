#!/usr/bin/env python3
"""Fetch, patch and build the native parts of the add-on.

Two targets:

``windows``
    Runs on Windows with Visual Studio (x64 tools). Builds the 64-bit
    ``mbrola.dll`` and an eSpeak NG DLL with MBROLA support, then stages them
    and ``espeak-ng-data`` into the add-on folder.

``linux-harness``
    Runs on Linux with gcc. Builds ``libmbrola.so`` and a ``libespeak-ng.so``
    whose MBROLA wrapper is replaced by ``native/linux-test-harness/mbrowrap_dlopen.c``
    so it uses the same library API as on Windows. Used only by the
    end-to-end tests; nothing from it is shipped.

The only dependencies are the standard library, ``git`` and ``cmake`` (plus a
C compiler). Each step is a small function so it can be tested separately.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
NATIVE_DIR = REPO_ROOT / "native"
DEFAULT_STAGE = REPO_ROOT / "addon" / "synthDrivers" / "mbrola_espeak"

TARGETS = ("windows", "linux-harness")

# Name of the eSpeak NG DLL inside the add-on. It deliberately differs from
# NVDA's own "espeak.dll" so the two can never be confused by the loader.
STAGED_ESPEAK_DLL = {"windows": "espeak-ng-mbrola.dll", "linux-harness": "libespeak-ng.so"}
STAGED_MBROLA_LIB = {"windows": "mbrola.dll", "linux-harness": "libmbrola.so"}


# Names left out of the staged espeak-ng-data (matched against every file and folder name).
STRIPPED_DATA = ("mbrola", "!v")


@dataclasses.dataclass(frozen=True)
class SourcePin:
	name: str
	repo: str
	ref: str
	commit: str


def load_pins(path: Path = NATIVE_DIR / "versions.json") -> dict[str, SourcePin]:
	data = json.loads(path.read_text(encoding="utf-8"))
	pins = {}
	for name, entry in data.items():
		if name.startswith("_"):
			continue
		pins[name] = SourcePin(name=name, repo=entry["repo"], ref=entry["ref"], commit=entry["commit"])
	return pins


def run(cmd: list[str], cwd: Path | None = None) -> None:
	print("+", " ".join(str(c) for c in cmd), flush=True)
	subprocess.run([str(c) for c in cmd], cwd=cwd, check=True)


def git_output(args: list[str], cwd: Path) -> str:
	return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def fetch_source(pin: SourcePin, dest: Path) -> Path:
	"""Check out exactly ``pin.commit`` into ``dest`` (reusing an existing checkout)."""
	if not (dest / ".git").exists():
		dest.mkdir(parents=True, exist_ok=True)
		run(["git", "init", "-q"], cwd=dest)
		run(["git", "remote", "add", "origin", pin.repo], cwd=dest)
	run(["git", "fetch", "-q", "--depth", "1", "origin", pin.commit], cwd=dest)
	run(["git", "checkout", "-q", "--force", pin.commit], cwd=dest)
	run(["git", "clean", "-q", "-fdx"], cwd=dest)
	actual = git_output(["rev-parse", "HEAD"], cwd=dest)
	if actual != pin.commit:
		raise RuntimeError(f"{pin.name}: expected commit {pin.commit}, got {actual}")
	return dest


def apply_patches(source_dir: Path, patch_dir: Path) -> list[Path]:
	"""Apply every ``*.patch`` in ``patch_dir`` in name order. Returns the patches applied."""
	applied = []
	for patch in sorted(patch_dir.glob("*.patch")):
		run(["git", "apply", "--whitespace=nowarn", str(patch)], cwd=source_dir)
		applied.append(patch)
	return applied


def cmake_build_type_args(target: str) -> list[str]:
	if target == "windows":
		# 64-bit only: NVDA 2026.1 and later run as a 64-bit process.
		return ["-A", "x64"]
	return ["-G", "Ninja" if shutil.which("ninja") else "Unix Makefiles", "-DCMAKE_BUILD_TYPE=Release"]


def mbrola_cmake_args(target: str, mbrola_src: Path) -> list[str]:
	return [*cmake_build_type_args(target), f"-DMBROLA_SOURCE_DIR={mbrola_src}"]


def espeak_cmake_args(target: str) -> list[str]:
	"""CMake options for eSpeak NG. Kept as data so tests can check them."""
	args = [
		*cmake_build_type_args(target),
		"-DBUILD_SHARED_LIBS=ON",
		"-DUSE_MBROLA=ON",
		# eSpeak NG only generates espeak-ng-data/mbrola_ph/*_phtrans when HAVE_MBROLA is
		# set, and it sets that only if it finds an `mbrola` *executable* at configure time.
		# We use the library instead and there is no executable on Windows, so force it.
		# Without this the MBROLA voices fail with "voice does not exist".
		"-DHAVE_MBROLA=ON",
		# NVDA plays the audio itself; eSpeak NG must not open an audio device.
		"-DUSE_LIBPCAUDIO=OFF",
		# Keep the build self-contained (no external libsonic).
		"-DUSE_LIBSONIC=OFF",
		"-DUSE_KLATT=ON",
		"-DUSE_SPEECHPLAYER=ON",
		"-DESPEAK_COMPAT=OFF",
		"-DBUILD_TESTING=OFF",
	]
	if target == "windows":
		args.append("-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded")
	else:
		# Async mode needs pthreads; we only use synchronous mode anyway.
		args.append("-DUSE_ASYNC=OFF")
	return args


def install_linux_harness_wrapper(espeak_src: Path) -> None:
	"""Swap eSpeak NG's pipe-based MBROLA wrapper for the dlopen() one."""
	shutil.copyfile(
		NATIVE_DIR / "linux-test-harness" / "mbrowrap_dlopen.c",
		espeak_src / "src" / "libespeak-ng" / "mbrowrap.c",
	)


def cmake_configure_and_build(source: Path, build: Path, args: list[str]) -> None:
	run(["cmake", "-S", source, "-B", build, *args])
	run(["cmake", "--build", build, "--config", "Release", "--parallel"])


def find_one(root: Path, patterns: list[str]) -> Path:
	for pattern in patterns:
		matches = sorted(p for p in root.rglob(pattern) if p.is_file())
		if matches:
			return matches[0]
	raise FileNotFoundError(f"none of {patterns} found under {root}")


def stage_outputs(target: str, mbrola_build: Path, espeak_build: Path, stage_dir: Path) -> dict[str, Path]:
	"""Copy the built libraries and data into ``stage_dir``.

	Layout (matches ``core/layout.py``)::

		<stage_dir>/bin/<espeak dll>
		<stage_dir>/bin/<mbrola dll>
		<stage_dir>/espeak-ng-data/...
	"""
	bin_dir = stage_dir / "bin"
	bin_dir.mkdir(parents=True, exist_ok=True)
	if target == "windows":
		espeak_lib = find_one(espeak_build, ["espeak-ng.dll", "libespeak-ng.dll"])
		mbrola_lib = find_one(mbrola_build, ["mbrola.dll"])
	else:
		espeak_lib = find_one(espeak_build, ["libespeak-ng.so.1", "libespeak-ng.so"])
		mbrola_lib = find_one(mbrola_build, ["libmbrola.so"])
	staged = {
		"espeak": bin_dir / STAGED_ESPEAK_DLL[target],
		"mbrola": bin_dir / STAGED_MBROLA_LIB[target],
		"data": stage_dir / "espeak-ng-data",
	}
	shutil.copyfile(espeak_lib, staged["espeak"])
	shutil.copyfile(mbrola_lib, staged["mbrola"])
	data_src = espeak_build / "espeak-ng-data"
	if staged["data"].exists():
		shutil.rmtree(staged["data"])
	# Never ship voice databases: they have their own licences and are imported by the user.
	# Also leave out eSpeak NG's voice variants (voices/!v: Alex, Michael, ...): the add-on
	# never offers variants, and MBROLA voices cannot use them.
	shutil.copytree(data_src, staged["data"], ignore=shutil.ignore_patterns(*STRIPPED_DATA))
	(staged["data"] / "mbrola").mkdir(exist_ok=True)
	return staged


def build(target: str, work_dir: Path, stage_dir: Path) -> dict[str, Path]:
	pins = load_pins()
	src_dir = work_dir / "src"
	mbrola_src = fetch_source(pins["mbrola"], src_dir / "mbrola")
	apply_patches(mbrola_src, NATIVE_DIR / "patches" / "mbrola")
	espeak_src = fetch_source(pins["espeak-ng"], src_dir / "espeak-ng")
	apply_patches(espeak_src, NATIVE_DIR / "patches" / "espeak-ng")
	if target == "linux-harness":
		install_linux_harness_wrapper(espeak_src)

	mbrola_build = work_dir / target / "mbrola"
	espeak_build = work_dir / target / "espeak-ng"
	cmake_configure_and_build(NATIVE_DIR / "mbrola", mbrola_build, mbrola_cmake_args(target, mbrola_src))
	cmake_configure_and_build(espeak_src, espeak_build, espeak_cmake_args(target))
	return stage_outputs(target, mbrola_build, espeak_build, stage_dir)


def parse_args(argv: list[str]) -> argparse.Namespace:
	parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
	parser.add_argument("--target", choices=TARGETS, required=True)
	parser.add_argument("--work-dir", type=Path, default=REPO_ROOT / "build")
	parser.add_argument(
		"--stage-dir",
		type=Path,
		default=None,
		help="Where to put the outputs (default: the add-on folder for windows, build/linux-stage for linux-harness)",
	)
	return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
	args = parse_args(sys.argv[1:] if argv is None else argv)
	stage = args.stage_dir
	if stage is None:
		stage = DEFAULT_STAGE if args.target == "windows" else args.work_dir / "linux-stage"
	staged = build(args.target, args.work_dir.resolve(), stage.resolve())
	for kind, path in staged.items():
		print(f"staged {kind}: {path}")
	return 0


if __name__ == "__main__":
	sys.exit(main())
