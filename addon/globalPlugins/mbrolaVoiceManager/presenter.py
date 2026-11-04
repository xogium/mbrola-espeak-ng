"""What the "MBROLA voices" settings panel shows and does, without any wx code.

The wx panel (``panel.py``) only displays what this class returns and
forwards button presses to it, so all of the behaviour is unit-tested.
Messages are plain sentences because they are read out by NVDA itself.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from pathlib import Path


@dataclasses.dataclass(frozen=True)
class VoiceEntry:
	name: str
	label: str


@dataclasses.dataclass(frozen=True)
class Outcome:
	message: str
	is_error: bool
	voices_changed: bool


class VoiceManagerPresenter:
	def __init__(
		self,
		library,
		expected_errors: tuple[type[BaseException], ...],
		translate: Callable[[str], str] = lambda s: s,
	):
		"""
		:param library: a ``core.voice_library.VoiceLibrary`` (or anything with the same methods).
		:param expected_errors: errors that are the user's problem (bad file, unknown name)
			and are shown as messages. Anything else propagates and gets logged by NVDA.
		:param translate: gettext function, so messages can be translated.
		"""
		self._library = library
		self._expected = expected_errors
		self._ = translate

	def entries(self) -> list[VoiceEntry]:
		_ = self._
		speakable = self._library.speakable_definitions()
		entries = []
		for voice in self._library.installed_voices():
			variants = [d.identifier for d in speakable if d.database == voice.name]
			label = _("{name}, {rate} Hz, voices: {variants}").format(
				name=voice.name,
				rate=voice.header.sample_rate,
				variants=", ".join(variants) or _("none"),
			)
			entries.append(VoiceEntry(voice.name, label))
		return entries

	def import_files(self, paths: Sequence[Path]) -> Outcome:
		_ = self._
		imported: list[str] = []
		problems: list[str] = []
		for path in paths:
			try:
				voices, report = self._library.import_path(Path(path))
			except self._expected as e:
				problems.append(f"{Path(path).name}: {e}")
				continue
			imported.extend(v.name for v in voices)
			problems.extend(
				_("{name} will be updated after NVDA restarts the synthesizer ({error})").format(name=n, error=err)
				for n, err in report.failed.items()
			)
		parts = []
		if imported:
			parts.append(_("Imported: {names}.").format(names=", ".join(sorted(set(imported)))))
		if problems:
			parts.append(_("Problems: {details}").format(details=" ".join(problems)))
		if not parts:
			parts.append(_("Nothing was imported."))
		return Outcome(" ".join(parts), is_error=not imported, voices_changed=bool(imported))

	def remove(self, name: str) -> Outcome:
		_ = self._
		try:
			report = self._library.remove(name)
		except self._expected as e:
			return Outcome(str(e), is_error=True, voices_changed=False)
		if name in report.failed:
			return Outcome(
				_("{name} was removed. Its file is still in use and will be deleted when the synthesizer restarts.").format(
					name=name,
				),
				is_error=False,
				voices_changed=True,
			)
		return Outcome(_("{name} was removed.").format(name=name), is_error=False, voices_changed=True)
