"""Make eSpeak NG's ``espeak-ng-data/mbrola`` folder match the voice store.

On Windows, eSpeak NG only looks for a database at ``<data>/mbrola/<name>``,
and that folder is inside the add-on, which gets replaced on every update.
So the voices live in the store and are mirrored here when the synthesizer
starts and after each import or removal.

A hard link is used when possible (no extra disk space, and the store and the
add-on are normally on the same drive under ``%APPDATA%\\nvda``). Otherwise the
file is copied.

Removing or replacing a database that eSpeak NG has open fails on Windows.
Those files are reported in :attr:`SyncReport.failed` and sorted out on the
next sync, once the synthesizer has been restarted.
"""

from __future__ import annotations

import dataclasses
import os
import shutil
from collections.abc import Callable, Iterable
from pathlib import Path

from .voice_store import InstalledVoice

Linker = Callable[[Path, Path], None]


def link_or_copy(source: Path, dest: Path) -> None:
	try:
		os.link(source, dest)
	except OSError:
		shutil.copy2(source, dest)


@dataclasses.dataclass
class SyncReport:
	added: list[str] = dataclasses.field(default_factory=list)
	removed: list[str] = dataclasses.field(default_factory=list)
	unchanged: list[str] = dataclasses.field(default_factory=list)
	failed: dict[str, str] = dataclasses.field(default_factory=dict)

	@property
	def ok(self) -> bool:
		return not self.failed


def _is_current(source: Path, dest: Path) -> bool:
	try:
		if os.path.samefile(source, dest):
			return True
		s, d = source.stat(), dest.stat()
	except OSError:
		return False
	return s.st_size == d.st_size and s.st_mtime_ns == d.st_mtime_ns


def sync_voices(
	voices: Iterable[InstalledVoice],
	target_dir: Path,
	managed_names: Iterable[str],
	linker: Linker = link_or_copy,
) -> SyncReport:
	"""Mirror ``voices`` into ``target_dir``.

	:param managed_names: Every database name this add-on may manage. Files in
		``target_dir`` with one of these names that are not in ``voices`` are
		deleted; anything else in the folder is left alone.
	:param linker: How to put a file in place (injected for tests).
	"""
	report = SyncReport()
	target_dir.mkdir(parents=True, exist_ok=True)
	wanted = {v.name: v for v in voices}

	for name, voice in sorted(wanted.items()):
		dest = target_dir / name
		if dest.exists() and _is_current(voice.path, dest):
			report.unchanged.append(name)
			continue
		try:
			if dest.exists():
				dest.unlink()
			linker(voice.path, dest)
			report.added.append(name)
		except OSError as e:
			report.failed[name] = str(e)

	for name in sorted(set(managed_names) - set(wanted)):
		dest = target_dir / name
		if not dest.is_file():
			continue
		try:
			dest.unlink()
			report.removed.append(name)
		except OSError as e:
			report.failed[name] = str(e)
	return report
