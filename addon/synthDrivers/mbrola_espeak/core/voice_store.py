"""The user's collection of imported MBROLA voice databases.

The store is a plain folder (normally ``<NVDA config>/mbrolaVoices``) holding
one file per database, named exactly as eSpeak NG expects (``en1``,
``us1``, ...). It lives outside the add-on folder so add-on updates do not
delete the voices.

Importing accepts a database file, a ``.zip`` archive containing one or
more databases, or a folder, which is searched (including subfolders) for
both. A folder is the easy way to import many voices at once: in the
https://github.com/numediart/MBROLA-voices collection every voice sits in
its own subfolder (``data/en1/en1``, ``data/us1/us1``, ...), so a file dialog
cannot select them together. Every candidate is checked with
:func:`voice_file.parse_header` before anything is written. Files are written
to a temporary name and then renamed, so a failed import never leaves a
half-written voice behind.
"""

from __future__ import annotations

import dataclasses
import os
import re
import tempfile
import zipfile
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from .errors import N_, InvalidVoiceFileError, NoVoicesFoundError, UnknownVoiceNameError, VoiceArchiveError
from .voice_file import HEADER_PROBE_SIZE, MbrolaVoiceHeader, parse_header, read_header_from_path

_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
# Largest real MBROLA databases are around 30 MB. Anything far bigger inside a zip is refused
# so that a malformed or malicious archive cannot fill the disk.
MAX_VOICE_BYTES = 256 * 1024 * 1024
# A folder scan stops after this many files, so picking C:\ by mistake ends quickly.
MAX_SCANNED_FILES = 50_000
_COPY_CHUNK = 1024 * 1024


@dataclasses.dataclass(frozen=True)
class InstalledVoice:
	name: str
	path: Path
	header: MbrolaVoiceHeader


def resolve_database_name(file_name: str, known_names: Iterable[str]) -> str | None:
	"""Work out which MBROLA database a file is, from its file name.

	``en1`` -> ``en1``; ``en1.dat`` or ``EN1`` -> ``en1``. Returns ``None`` if
	the name does not match any database eSpeak NG has a definition for.
	"""
	known = set(known_names)
	base = PurePosixPath(file_name.replace("\\", "/")).name
	candidates = [base, base.lower()]
	stem = base.split(".", 1)[0]
	candidates += [stem, stem.lower()]
	for candidate in candidates:
		if candidate in known and _SAFE_NAME_RE.match(candidate):
			return candidate
	return None


class VoiceStore:
	def __init__(self, root: Path, known_names: Iterable[str]):
		"""
		:param root: Folder holding the voices. Created on first import.
		:param known_names: Database names eSpeak NG has definitions for (from :class:`VoiceCatalog`).
		"""
		self._root = Path(root)
		self._known = frozenset(known_names)

	@property
	def root(self) -> Path:
		return self._root

	def installed(self) -> list[InstalledVoice]:
		"""Valid voices in the store, sorted by name. Invalid or unknown files are ignored."""
		if not self._root.is_dir():
			return []
		voices = []
		for path in sorted(self._root.iterdir()):
			if not path.is_file() or path.name not in self._known:
				continue
			try:
				header = read_header_from_path(path)
			except InvalidVoiceFileError:
				continue
			voices.append(InstalledVoice(name=path.name, path=path, header=header))
		return voices

	def installed_names(self) -> frozenset[str]:
		return frozenset(v.name for v in self.installed())

	def import_path(self, source: Path, name: str | None = None) -> list[InstalledVoice]:
		"""Import a voice file or a zip of voice files. Returns what was installed.

		:param name: Database name to use for a single file whose file name is not
			recognisable (ignored for zip archives and folders).
		:raises InvalidVoiceFileError, UnknownVoiceNameError, VoiceArchiveError, NoVoicesFoundError:
		"""
		source = Path(source)
		if source.is_dir():
			return self._import_directory(source)
		if zipfile.is_zipfile(source):
			return self._import_zip(source)
		return [self._import_file(source, name)]

	def remove(self, name: str) -> None:
		if name not in self._known:
			# Translators: {name} is what the user asked to remove.
			raise UnknownVoiceNameError(N_("{name} is not an MBROLA voice name."), name=name)
		path = self._root / name
		if path.exists():
			path.unlink()

	def _resolve_name(self, file_name: str, override: str | None) -> str:
		if override is not None:
			if override not in self._known or not _SAFE_NAME_RE.match(override):
				# Translators: {name} is a voice name such as en1.
				raise UnknownVoiceNameError(N_("eSpeak NG has no MBROLA voice named {name}."), name=override)
			return override
		resolved = resolve_database_name(file_name, self._known)
		if resolved is None:
			raise UnknownVoiceNameError(
				# Translators: {file} is the name of the file the user picked. en1 and de6 are voice names; keep them.
				N_("Cannot tell which MBROLA voice {file} is. Keep the original file name, for example en1 or de6."),
				file=file_name,
			)
		return resolved

	def _import_file(self, source: Path, name: str | None) -> InstalledVoice:
		voice_name = self._resolve_name(source.name, name)
		header = read_header_from_path(source)
		try:
			with open(source, "rb") as f:
				dest = self._write_atomically(voice_name, f, limit=None)
		except OSError as e:
			raise InvalidVoiceFileError(
				# Translators: {file} is a file name, {reason} the system's error message.
				N_("Could not copy {file}: {reason}"),
				file=source.name,
				reason=e.strerror or str(e),
			) from e
		return InstalledVoice(name=voice_name, path=dest, header=header)

	def _import_zip(self, source: Path) -> list[InstalledVoice]:
		imported = []
		try:
			with zipfile.ZipFile(source) as archive:
				for info in archive.infolist():
					voice = self._import_zip_member(archive, info)
					if voice is not None:
						imported.append(voice)
		except (zipfile.BadZipFile, OSError) as e:
			raise VoiceArchiveError(
				# Translators: {file} is a zip file name, {reason} the error.
				N_("Could not read the archive {file}: {reason}"),
				file=source.name,
				reason=str(e),
			) from e
		if not imported:
			raise VoiceArchiveError(
				# Translators: {file} is a zip file name.
				N_("{file} does not contain any MBROLA voice that eSpeak NG can use."),
				file=source.name,
			)
		return imported

	def _import_directory(self, folder: Path) -> list[InstalledVoice]:
		"""Import every voice file and voice zip found under ``folder``.

		Files that are not voices are skipped silently (READMEs, licences, test
		files). Symbolic links and junctions are not followed, and the voice store
		itself is never scanned.
		"""
		imported: dict[str, InstalledVoice] = {}
		scanned = 0
		store = self._root.resolve() if self._root.exists() else None
		for dirpath, dirnames, filenames in os.walk(folder, followlinks=False):
			here = Path(dirpath)
			if store is not None and here.resolve() == store:
				dirnames[:] = []
				continue
			dirnames.sort()
			for file_name in sorted(filenames):
				scanned += 1
				if scanned > MAX_SCANNED_FILES:
					break
				path = here / file_name
				if path.is_symlink() or not path.is_file():
					continue
				for voice in self._try_import_candidate(path):
					imported[voice.name] = voice
			if scanned > MAX_SCANNED_FILES:
				break
		if not imported:
			raise NoVoicesFoundError(
				# Translators: {folder} is the folder the user picked.
				N_("No MBROLA voices that eSpeak NG can use were found in {folder}."),
				folder=str(folder),
			)
		return [imported[name] for name in sorted(imported)]

	def _try_import_candidate(self, path: Path) -> list[InstalledVoice]:
		"""Import ``path`` if it is a voice or a zip with voices; otherwise return nothing."""
		if path.suffix.lower() == ".zip":
			try:
				return self._import_zip(path)
			except VoiceArchiveError:
				return []
		if resolve_database_name(path.name, self._known) is None:
			return []
		try:
			if path.stat().st_size > MAX_VOICE_BYTES:
				return []
			return [self._import_file(path, None)]
		except (InvalidVoiceFileError, OSError):
			return []

	def _import_zip_member(self, archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> InstalledVoice | None:
		if info.is_dir() or info.file_size > MAX_VOICE_BYTES:
			return None
		# Only the base name is ever used, so paths like "../../x" cannot escape the store.
		voice_name = resolve_database_name(info.filename, self._known)
		if voice_name is None:
			return None
		with archive.open(info) as member:
			try:
				header = parse_header(member.read(HEADER_PROBE_SIZE))
			except InvalidVoiceFileError:
				return None
		with archive.open(info) as member:
			dest = self._write_atomically(voice_name, member, limit=MAX_VOICE_BYTES)
		return InstalledVoice(name=voice_name, path=dest, header=header)

	def _write_atomically(self, voice_name: str, stream: BinaryIO, limit: int | None) -> Path:
		self._root.mkdir(parents=True, exist_ok=True)
		dest = self._root / voice_name
		fd, tmp_name = tempfile.mkstemp(prefix=f".{voice_name}.", suffix=".partial", dir=self._root)
		tmp = Path(tmp_name)
		try:
			written = 0
			with os.fdopen(fd, "wb") as out:
				while chunk := stream.read(_COPY_CHUNK):
					written += len(chunk)
					if limit is not None and written > limit:
						raise VoiceArchiveError(
							# Translators: {name} is a voice name such as en1, found in a zip file.
							N_("{name} is larger than expected; refusing to import it."),
							name=voice_name,
						)
					out.write(chunk)
			os.replace(tmp, dest)
		except BaseException:
			tmp.unlink(missing_ok=True)
			raise
		return dest
