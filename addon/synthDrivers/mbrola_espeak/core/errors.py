"""Exception types raised by the core package, and how their messages get translated.

Everything the core raises on purpose derives from :class:`MbrolaEspeakError`,
so callers in the NVDA layer can catch one type and show its message.

The core never imports gettext: NVDA installs an add-on's translations only
into modules of that add-on, through ``addonHandler.initTranslation()``.
Messages a user may see are therefore raised as an English template marked
with :func:`N_`, plus named values. ``str(error)`` is the English text (for
logs and tests); the NVDA layer calls :meth:`MbrolaEspeakError.translated`
with its own gettext function. ``tools/i18n.py`` collects every ``N_()``
string together with the ``_()`` strings of the NVDA layer.
"""

from __future__ import annotations

from collections.abc import Callable


def N_(message: str) -> str:
	"""Mark ``message`` for translation without translating it (gettext's usual no-op marker)."""
	return message


class MbrolaEspeakError(Exception):
	"""Base class for all errors raised on purpose by this package."""

	def __init__(self, message: str, **params: object):
		"""
		:param message: English text. With ``params`` it is a ``str.format`` template
			such as ``N_("Could not read {file}: {reason}")``.
		:param params: values for the template's ``{placeholders}``.
		"""
		self.template = message
		self.params = params
		super().__init__(message.format(**params) if params else message)

	def translated(self, translate: Callable[[str], str]) -> str:
		"""The message in the user's language. Falls back to English if a translation is broken."""
		text = translate(self.template)
		if not self.params:
			return text
		try:
			return text.format(**self.params)
		except (KeyError, IndexError, ValueError):
			return str(self)


class InvalidVoiceFileError(MbrolaEspeakError):
	"""A file is not a usable MBROLA voice database."""


class UnknownVoiceNameError(MbrolaEspeakError):
	"""The MBROLA database name could not be found, or eSpeak NG has no definition for it."""


class VoiceArchiveError(MbrolaEspeakError):
	"""A zip archive could not be imported."""


class NoVoicesFoundError(MbrolaEspeakError):
	"""A folder was searched but contained no usable MBROLA voice."""


class NativeLibraryError(MbrolaEspeakError):
	"""A native library (eSpeak NG or MBROLA) failed to load or returned an error."""
