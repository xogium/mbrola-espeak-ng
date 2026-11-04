"""The speech items the core understands.

These are small, NVDA-independent versions of NVDA's ``speech.commands``.
``synthDrivers/mbrola_espeak/_nvda_commands.py`` converts NVDA's objects into
these, so the SSML builder can be tested without NVDA.
"""

from __future__ import annotations

import dataclasses
from typing import Literal, Union


@dataclasses.dataclass(frozen=True)
class Text:
	text: str


@dataclasses.dataclass(frozen=True)
class Index:
	"""Report back when speech reaches this point (NVDA uses it for say-all and cursor tracking)."""

	index: int


@dataclasses.dataclass(frozen=True)
class CharacterMode:
	"""Spell out text one character at a time while ``on`` is true."""

	on: bool


@dataclasses.dataclass(frozen=True)
class LangChange:
	"""Switch language. ``None`` means go back to the voice's own language."""

	lang: str | None


@dataclasses.dataclass(frozen=True)
class Break:
	milliseconds: int


ProsodyAttribute = Literal["pitch", "rate", "volume"]


@dataclasses.dataclass(frozen=True)
class Prosody:
	"""Change pitch, rate or volume relative to the current setting. 1.0 means back to normal."""

	attribute: ProsodyAttribute
	multiplier: float


SpeechItem = Union[Text, Index, CharacterMode, LangChange, Break, Prosody]
