"""Convert an NVDA speech sequence into core speech items.

This is the only module that knows NVDA's ``speech.commands`` classes on the
speech path. It has no other logic.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from speech.commands import (
	BreakCommand,
	CharacterModeCommand,
	IndexCommand,
	LangChangeCommand,
	PhonemeCommand,
	PitchCommand,
	RateCommand,
	VolumeCommand,
)

from .core.speech_items import Break, CharacterMode, Index, Prosody, SpeechItem, Text

SUPPORTED_COMMANDS = frozenset(
	{
		IndexCommand,
		CharacterModeCommand,
		BreakCommand,
		PitchCommand,
		RateCommand,
		VolumeCommand,
		PhonemeCommand,
	},
)
"""Commands advertised to NVDA. LangChangeCommand is left out on purpose: see docs/ARCHITECTURE.md."""

_PROSODY = {PitchCommand: "pitch", RateCommand: "rate", VolumeCommand: "volume"}


def to_speech_items(sequence: Iterable[object], on_unknown: Callable[[object], None]) -> list[SpeechItem]:
	items: list[SpeechItem] = []
	for item in sequence:
		if isinstance(item, str):
			items.append(Text(item))
		elif isinstance(item, IndexCommand):
			items.append(Index(item.index))
		elif isinstance(item, CharacterModeCommand):
			items.append(CharacterMode(bool(item.state)))
		elif isinstance(item, BreakCommand):
			items.append(Break(item.time))
		elif type(item) in _PROSODY:
			items.append(Prosody(_PROSODY[type(item)], item.multiplier))
		elif isinstance(item, PhonemeCommand):
			# eSpeak NG phoneme input is not IPA; fall back to the plain text, as NVDA intends.
			if item.text:
				items.append(Text(item.text))
		elif isinstance(item, LangChangeCommand):
			# Not advertised, so NVDA should not send it; ignore it if it does.
			pass
		else:
			on_unknown(item)
	return items
