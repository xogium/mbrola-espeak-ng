"""ctypes binding to the eSpeak NG library that was built with MBROLA support.

This module only translates between Python and C. It has no threads and no
audio handling (see :mod:`engine`). Struct layouts come from
``src/include/espeak-ng/speak_lib.h`` and are correct for 32-bit and 64-bit
builds because ctypes applies the platform's alignment rules.

Loading order matters on Windows: eSpeak NG calls ``LoadLibraryA("mbrola.dll")``
with a bare name, and Windows searches NVDA's program folder, not the add-on's.
If a module with that name is already loaded in the process, Windows reuses it.
So we load ``mbrola.dll`` from its full path *first*. The Linux test harness
does the same with ``dlopen("libmbrola.so")``.
"""

from __future__ import annotations

import ctypes
import dataclasses
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .errors import NativeLibraryError

AUDIO_OUTPUT_SYNCHRONOUS = 2
espeakINITIALIZE_DONT_EXIT = 0x8000
espeakCHARS_UTF8 = 1
espeakSSML = 0x10

EE_OK = 0

espeakEVENT_LIST_TERMINATED = 0
espeakEVENT_MARK = 3
espeakEVENT_MSG_TERMINATED = 6
espeakEVENT_SAMPLERATE = 8

CALLBACK_CONTINUE = 0
CALLBACK_ABORT = 1


class _EventId(ctypes.Union):
	_fields_ = (("number", ctypes.c_int), ("name", ctypes.c_char_p), ("string", ctypes.c_char * 8))


class EspeakEvent(ctypes.Structure):
	_fields_ = (
		("type", ctypes.c_int),
		("unique_identifier", ctypes.c_uint),
		("text_position", ctypes.c_int),
		("length", ctypes.c_int),
		("audio_position", ctypes.c_int),
		("sample", ctypes.c_int),
		("user_data", ctypes.c_void_p),
		("id", _EventId),
	)


class EspeakVoice(ctypes.Structure):
	_fields_ = (
		("name", ctypes.c_char_p),
		("languages", ctypes.c_char_p),
		("identifier", ctypes.c_char_p),
		("gender", ctypes.c_ubyte),
		("age", ctypes.c_ubyte),
		("variant", ctypes.c_ubyte),
		("xx1", ctypes.c_ubyte),
		("score", ctypes.c_int),
		("spare", ctypes.c_void_p),
	)


SynthCallbackType = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(EspeakEvent))


@dataclasses.dataclass(frozen=True)
class SynthEvent:
	"""A Python copy of the events the engine cares about."""

	type: int
	audio_position_ms: int
	sample: int
	"""Sample count from the start of the utterance (``espeak_EVENT.sample``)."""
	mark: str | None = None
	number: int | None = None


@dataclasses.dataclass(frozen=True)
class AudioBlock:
	data: bytes
	events: tuple[SynthEvent, ...]


AudioHandler = Callable[[AudioBlock], bool]
"""Receives each block of synthesized audio. Returns ``False`` to abort synthesis."""


def _default_loader(path: Path) -> Any:
	# Neither library depends on anything outside Windows itself (static C runtime),
	# so the default search flags are fine.
	return ctypes.CDLL(str(path))


def decode_events(events_ptr) -> tuple[SynthEvent, ...]:
	"""Copy the C event list (terminated by espeakEVENT_LIST_TERMINATED) into Python objects."""
	out = []
	if not events_ptr:
		return ()
	i = 0
	while True:
		e = events_ptr[i]
		if e.type == espeakEVENT_LIST_TERMINATED:
			break
		if e.type == espeakEVENT_MARK:
			name = e.id.name.decode("utf-8", "replace") if e.id.name else None
			out.append(SynthEvent(e.type, e.audio_position, e.sample, mark=name))
		elif e.type == espeakEVENT_SAMPLERATE:
			out.append(SynthEvent(e.type, e.audio_position, e.sample, number=e.id.number))
		else:
			out.append(SynthEvent(e.type, e.audio_position, e.sample))
		i += 1
	return tuple(out)


class EspeakBinding:
	"""One loaded and initialized eSpeak NG instance.

	eSpeak NG keeps global state, so only one instance should exist per process.
	All methods except :meth:`synth` return quickly. :meth:`synth` blocks until
	the text has been synthesized (or aborted by the handler) and must be called
	from a single thread.
	"""

	def __init__(
		self,
		espeak_library: Path,
		mbrola_library: Path,
		espeak_home: Path,
		loader: Callable[[Path], Any] = _default_loader,
	):
		for p in (espeak_library, mbrola_library):
			if not Path(p).is_file():
				raise NativeLibraryError(f"Missing native library: {p}")
		try:
			# Order matters: see the module docstring.
			self._mbrola = loader(Path(mbrola_library))
			self._dll = loader(Path(espeak_library))
		except OSError as e:
			raise NativeLibraryError(f"Could not load the speech libraries: {e}") from e
		self._declare_prototypes()
		self._handler: AudioHandler | None = None
		self._callback_error: BaseException | None = None
		# Keep a reference: ctypes callbacks are freed when garbage-collected.
		self._c_callback = SynthCallbackType(self._on_synth)
		rate = self._dll.espeak_Initialize(
			AUDIO_OUTPUT_SYNCHRONOUS,
			300,
			os.fsencode(str(espeak_home)),
			espeakINITIALIZE_DONT_EXIT,
		)
		if rate <= 0:
			raise NativeLibraryError(f"espeak_Initialize failed ({rate}); data folder: {espeak_home}")
		self._initial_rate = rate
		self._dll.espeak_SetSynthCallback(self._c_callback)

	def _declare_prototypes(self) -> None:
		d = self._dll
		d.espeak_Initialize.argtypes = (ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int)
		d.espeak_Initialize.restype = ctypes.c_int
		d.espeak_SetSynthCallback.argtypes = (SynthCallbackType,)
		d.espeak_SetSynthCallback.restype = None
		d.espeak_Synth.argtypes = (
			ctypes.c_char_p,
			ctypes.c_size_t,
			ctypes.c_uint,
			ctypes.c_int,
			ctypes.c_uint,
			ctypes.c_uint,
			ctypes.POINTER(ctypes.c_uint),
			ctypes.c_void_p,
		)
		d.espeak_Synth.restype = ctypes.c_int
		d.espeak_SetVoiceByName.argtypes = (ctypes.c_char_p,)
		d.espeak_SetVoiceByName.restype = ctypes.c_int
		d.espeak_SetParameter.argtypes = (ctypes.c_int, ctypes.c_int, ctypes.c_int)
		d.espeak_SetParameter.restype = ctypes.c_int
		d.espeak_GetParameter.argtypes = (ctypes.c_int, ctypes.c_int)
		d.espeak_GetParameter.restype = ctypes.c_int
		d.espeak_ListVoices.argtypes = (ctypes.POINTER(EspeakVoice),)
		d.espeak_ListVoices.restype = ctypes.POINTER(ctypes.POINTER(EspeakVoice))
		d.espeak_Info.argtypes = (ctypes.POINTER(ctypes.c_char_p),)
		d.espeak_Info.restype = ctypes.c_char_p
		d.espeak_ng_GetSampleRate.argtypes = ()
		d.espeak_ng_GetSampleRate.restype = ctypes.c_int
		d.espeak_ng_Cancel.argtypes = ()
		d.espeak_ng_Cancel.restype = ctypes.c_int
		d.espeak_Terminate.argtypes = ()
		d.espeak_Terminate.restype = ctypes.c_int

	# --- queries -------------------------------------------------------------

	def version(self) -> str:
		return (self._dll.espeak_Info(None) or b"").decode("utf-8", "replace")

	def sample_rate(self) -> int:
		return self._dll.espeak_ng_GetSampleRate()

	def list_voice_identifiers(self) -> list[str]:
		voices = self._dll.espeak_ListVoices(None)
		ids = []
		i = 0
		while voices and voices[i]:
			ids.append(voices[i].contents.identifier.decode("utf-8", "replace"))
			i += 1
		return ids

	def get_parameter(self, parameter: int) -> int:
		return self._dll.espeak_GetParameter(int(parameter), 1)

	# --- commands ------------------------------------------------------------

	def set_voice(self, identifier: str) -> None:
		rc = self._dll.espeak_SetVoiceByName(identifier.encode("utf-8"))
		if rc != EE_OK:
			raise NativeLibraryError(
				f"eSpeak NG could not select voice {identifier} (error {rc}). "
				"Is the MBROLA voice file installed?",
			)

	def set_parameter(self, parameter: int, value: int) -> None:
		rc = self._dll.espeak_SetParameter(int(parameter), int(value), 0)
		if rc != EE_OK:
			raise NativeLibraryError(f"espeak_SetParameter({parameter}, {value}) failed ({rc})")

	def cancel(self) -> None:
		self._dll.espeak_ng_Cancel()

	def synth(self, ssml: str, handler: AudioHandler) -> int:
		"""Synthesize ``ssml``, calling ``handler`` for every audio block. Returns the eSpeak status.

		If ``handler`` raises, synthesis is aborted and the exception is re-raised here.
		"""
		data = ssml.encode("utf-8", errors="ignore")
		self._handler = handler
		self._callback_error = None
		try:
			rc = self._dll.espeak_Synth(data, len(data) + 1, 0, 0, 0, espeakCHARS_UTF8 | espeakSSML, None, None)
		finally:
			self._handler = None
		error, self._callback_error = self._callback_error, None
		if error is not None:
			raise error
		return rc

	def terminate(self) -> None:
		self._dll.espeak_Terminate()

	# --- callback ------------------------------------------------------------

	def _on_synth(self, wav, numsamples, events) -> int:
		handler = self._handler
		if handler is None:
			return CALLBACK_ABORT
		try:
			data = ctypes.string_at(wav, numsamples * 2) if wav and numsamples > 0 else b""
			keep_going = handler(AudioBlock(data=data, events=decode_events(events)))
		except BaseException as e:  # never let an exception unwind through C; synth() re-raises it
			self._callback_error = e
			return CALLBACK_ABORT
		return CALLBACK_CONTINUE if keep_going else CALLBACK_ABORT
