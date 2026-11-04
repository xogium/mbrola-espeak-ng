"""The list of MBROLA voices that eSpeak NG knows how to drive.

eSpeak NG ships one small text file per MBROLA voice variant in
``espeak-ng-data/voices/mb`` (for example ``mb-en1``)::

    name english-mb-en1
    language en-uk  3
    language en 2
    gender male
    mbrola en1 en1_phtrans

The ``mbrola`` line names the MBROLA database (``en1``) and the phoneme
translation table. Several definitions can share one database (``mb-br1``
and ``mb-br1-xex`` both use ``br1``).

This module only parses those files. Whether a database is actually installed
is decided by :mod:`voice_store`.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path


@dataclasses.dataclass(frozen=True)
class MbrolaVoiceDefinition:
	identifier: str
	"""eSpeak NG voice identifier, the file name, e.g. ``mb-en1``. Passed to espeak_SetVoiceByName."""
	name: str
	"""Human-readable name from the ``name`` line, e.g. ``english-mb-en1``."""
	database: str
	"""MBROLA database name, e.g. ``en1``."""
	languages: tuple[str, ...]
	"""Language tags in file order, e.g. ``("en-uk", "en-gb", "en")``."""
	gender: str | None

	@property
	def primary_language(self) -> str | None:
		return self.languages[0] if self.languages else None


def parse_definition(identifier: str, text: str) -> MbrolaVoiceDefinition | None:
	"""Parse one voice definition file. Returns ``None`` if it has no ``mbrola`` line."""
	name = identifier
	database = None
	languages: list[str] = []
	gender = None
	for raw_line in text.splitlines():
		line = raw_line.split("//", 1)[0].strip()
		if not line:
			continue
		key, _, rest = line.partition(" ")
		fields = rest.split()
		if key == "name" and fields:
			name = rest.strip()
		elif key == "language" and fields:
			languages.append(fields[0])
		elif key == "gender" and fields:
			gender = fields[0]
		elif key == "mbrola" and fields:
			database = fields[0]
	if database is None:
		return None
	return MbrolaVoiceDefinition(
		identifier=identifier,
		name=name,
		database=database,
		languages=tuple(languages),
		gender=gender,
	)


class VoiceCatalog:
	"""All MBROLA voice definitions found in one ``voices/mb`` folder."""

	def __init__(self, definitions: list[MbrolaVoiceDefinition]):
		self._definitions = sorted(definitions, key=lambda d: d.identifier)

	@classmethod
	def load(cls, definitions_dir: Path) -> "VoiceCatalog":
		definitions = []
		if definitions_dir.is_dir():
			for path in definitions_dir.iterdir():
				if not path.is_file():
					continue
				parsed = parse_definition(path.name, path.read_text(encoding="utf-8", errors="replace"))
				if parsed is not None:
					definitions.append(parsed)
		return cls(definitions)

	@property
	def definitions(self) -> tuple[MbrolaVoiceDefinition, ...]:
		return tuple(self._definitions)

	@property
	def database_names(self) -> frozenset[str]:
		return frozenset(d.database for d in self._definitions)

	def knows_database(self, database: str) -> bool:
		return database in self.database_names

	def for_databases(self, installed: set[str] | frozenset[str]) -> list[MbrolaVoiceDefinition]:
		"""Definitions whose database is in ``installed``, i.e. the voices that can speak."""
		return [d for d in self._definitions if d.database in installed]

	def by_identifier(self, identifier: str) -> MbrolaVoiceDefinition | None:
		for d in self._definitions:
			if d.identifier == identifier:
				return d
		return None
