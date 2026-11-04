"""Exception types raised by the core package.

Everything the core raises on purpose derives from :class:`MbrolaEspeakError`,
so callers in the NVDA layer can catch one type and show its message.
"""


class MbrolaEspeakError(Exception):
	"""Base class for all errors raised on purpose by this package."""


class InvalidVoiceFileError(MbrolaEspeakError):
	"""A file is not a usable MBROLA voice database."""


class UnknownVoiceNameError(MbrolaEspeakError):
	"""The MBROLA database name could not be found, or eSpeak NG has no definition for it."""


class VoiceArchiveError(MbrolaEspeakError):
	"""A zip archive could not be imported."""


class NativeLibraryError(MbrolaEspeakError):
	"""A native library (eSpeak NG or MBROLA) failed to load or returned an error."""
