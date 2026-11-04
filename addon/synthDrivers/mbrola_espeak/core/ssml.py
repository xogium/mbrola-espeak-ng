"""Turn a list of :mod:`speech_items` into the SSML subset eSpeak NG accepts.

Unlike NVDA's built-in eSpeak driver, this builder keeps the tags properly
nested. When an outer tag has to change, the tags opened inside it are closed
first and opened again afterwards.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from .speech_items import Break, CharacterMode, Index, LangChange, Prosody, SpeechItem, Text

_TEXT_ESCAPES = str.maketrans(
	{
		"\x01": None,  # eSpeak NG uses 0x01 for embedded commands
		"&": "&amp;",
		"<": "&lt;",
		">": "&gt;",
	},
)
_LANG_RE = re.compile(r"^[A-Za-z]{1,8}(?:[-_][A-Za-z0-9]{1,8})*$")
_PROSODY_ORDER = ("rate", "pitch", "volume")
# eSpeak NG ignores silly values, but keep the SSML sane.
_MAX_BREAK_MS = 10_000


def escape_text(text: str) -> str:
	return text.translate(_TEXT_ESCAPES)


def normalize_lang(lang: str) -> str | None:
	"""NVDA uses ``en_US``; SSML uses ``en-US``. Returns ``None`` for unusable tags."""
	if not _LANG_RE.match(lang):
		return None
	return lang.replace("_", "-")


class _State:
	def __init__(self) -> None:
		self.lang: str | None = None
		self.prosody: dict[str, int] = {}
		self.characters = False


def _open_tags(state: _State) -> str:
	parts = []
	if state.lang is not None:
		parts.append(f'<voice xml:lang="{state.lang}">')
	if state.prosody:
		attrs = "".join(f' {a}="{state.prosody[a]}%"' for a in _PROSODY_ORDER if a in state.prosody)
		parts.append(f"<prosody{attrs}>")
	if state.characters:
		parts.append('<say-as interpret-as="characters">')
	return "".join(parts)


def _close_tags(state: _State) -> str:
	parts = []
	if state.characters:
		parts.append("</say-as>")
	if state.prosody:
		parts.append("</prosody>")
	if state.lang is not None:
		parts.append("</voice>")
	return "".join(parts)


def build_ssml(items: Iterable[SpeechItem]) -> str:
	"""Build the markup for one utterance. Unknown item types raise ``TypeError``.

	Tags are opened lazily, just before the next piece of content, so a
	change that is immediately followed by another change, or by the end of
	the utterance, produces no empty tag pairs.
	"""
	out: list[str] = []
	state = _State()
	is_open = False

	def before_change() -> None:
		nonlocal is_open
		if is_open:
			out.append(_close_tags(state))
			is_open = False

	def emit(content: str) -> None:
		nonlocal is_open
		if not is_open:
			out.append(_open_tags(state))
			is_open = True
		out.append(content)

	for item in items:
		if isinstance(item, Text):
			emit(escape_text(item.text))
		elif isinstance(item, Index):
			emit(f'<mark name="{int(item.index)}"/>')
		elif isinstance(item, Break):
			ms = max(0, min(int(item.milliseconds), _MAX_BREAK_MS))
			emit(f'<break time="{ms}ms"/>')
		elif isinstance(item, CharacterMode):
			if item.on != state.characters:
				before_change()
				state.characters = item.on
		elif isinstance(item, LangChange):
			lang = normalize_lang(item.lang) if item.lang else None
			if lang != state.lang:
				before_change()
				state.lang = lang
		elif isinstance(item, Prosody):
			percent = int(round(item.multiplier * 100))
			new_value = None if percent == 100 else max(1, percent)
			if state.prosody.get(item.attribute) != new_value:
				before_change()
				if new_value is None:
					state.prosody.pop(item.attribute, None)
				else:
					state.prosody[item.attribute] = new_value
		else:
			raise TypeError(f"unsupported speech item: {item!r}")
	before_change()
	return "".join(out)
