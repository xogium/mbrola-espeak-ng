"""Speech engine: one worker thread that owns every native call.

Responsibilities:

* run eSpeak NG on a background thread so NVDA never blocks on synthesis;
* keep commands in order (voice, parameter and speech commands share one queue);
* split audio at index marks and report each index when its audio has played;
* cancel quickly.

How cancelling works: every utterance records the *generation* it was queued
in. :meth:`SpeechEngine.cancel` increments the generation and stops the audio
sink. The worker skips stale utterances, and the synthesis callback aborts as
soon as it sees that the generation has changed. Voice and parameter commands
are never dropped.

The engine depends only on two interfaces, which keeps it testable without NVDA
or a sound card:

* an :class:`EspeakLike` (normally :class:`espeak_binding.EspeakBinding`);
* an :class:`audio.AudioSink`.
"""

from __future__ import annotations

import concurrent.futures
import dataclasses
import queue
import threading
from collections.abc import Callable
from typing import Any, Protocol

from .audio import AudioSink, split_at_marks
from .espeak_binding import AudioBlock, espeakEVENT_MARK
from .params import EspeakParameter


class EspeakLike(Protocol):
	def sample_rate(self) -> int: ...
	def set_voice(self, identifier: str) -> None: ...
	def set_parameter(self, parameter: int, value: int) -> None: ...
	def synth(self, ssml: str, handler: Callable[[AudioBlock], bool]) -> int: ...
	def cancel(self) -> None: ...
	def terminate(self) -> None: ...


IndexCallback = Callable[[int], None]
DoneCallback = Callable[[], None]
ErrorCallback = Callable[[BaseException], None]


@dataclasses.dataclass
class _Task:
	func: Callable[[], Any] | None
	future: concurrent.futures.Future
	generation: int | None = None
	"""Set for speech tasks only: the task is skipped if the generation has moved on."""


class SpeechEngine:
	def __init__(
		self,
		espeak: EspeakLike,
		sink: AudioSink,
		on_index: IndexCallback,
		on_done: DoneCallback,
		on_error: ErrorCallback,
	):
		self._espeak = espeak
		self._sink = sink
		self._on_index = on_index
		self._on_done = on_done
		self._on_error = on_error
		self._queue: queue.Queue[_Task] = queue.Queue()
		self._generation = 0
		self._generation_lock = threading.Lock()
		self._parameters: dict[EspeakParameter, int] = {}
		self._voice: str | None = None
		self._sample_rate = 0
		self._terminated = False
		self._thread = threading.Thread(target=self._run, name="mbrola_espeak.SpeechEngine", daemon=True)
		self._thread.start()
		self.submit(self._refresh_sample_rate).result()

	# --- public API (any thread) --------------------------------------------

	@property
	def voice(self) -> str | None:
		return self._voice

	@property
	def sample_rate(self) -> int:
		return self._sample_rate

	def get_parameter(self, parameter: EspeakParameter) -> int | None:
		return self._parameters.get(parameter)

	def submit(self, func: Callable[[], Any]) -> concurrent.futures.Future:
		"""Run ``func`` on the worker thread after everything queued so far."""
		return self._put(_Task(func=func, future=concurrent.futures.Future()))

	def set_voice(self, identifier: str) -> concurrent.futures.Future:
		"""Select a voice. The returned future fails if eSpeak NG rejects it."""

		def apply() -> None:
			self._espeak.set_voice(identifier)
			self._voice = identifier
			# eSpeak NG resets prosody parameters when the voice changes.
			for parameter, value in self._parameters.items():
				self._espeak.set_parameter(parameter, value)
			self._refresh_sample_rate()

		return self.submit(apply)

	def set_parameter(self, parameter: EspeakParameter, value: int) -> concurrent.futures.Future:
		self._parameters[parameter] = value
		return self.submit(lambda: self._espeak.set_parameter(parameter, value))

	def speak(self, ssml: str) -> concurrent.futures.Future:
		with self._generation_lock:
			generation = self._generation
		return self._put(
			_Task(func=lambda: self._speak(ssml, generation), future=concurrent.futures.Future(), generation=generation),
		)

	def cancel(self) -> None:
		with self._generation_lock:
			self._generation += 1
		self._sink.stop()

	def pause(self, paused: bool) -> None:
		self._sink.pause(paused)

	def wait_until_idle(self, timeout: float | None = None) -> None:
		"""Block until everything queued so far has run (used by tests and shutdown)."""
		self.submit(lambda: None).result(timeout)

	def terminate(self) -> None:
		if self._terminated:
			return
		self._terminated = True
		self.cancel()
		self._queue.put(_Task(func=None, future=concurrent.futures.Future()))
		self._thread.join()
		try:
			self._espeak.terminate()
		finally:
			self._sink.close()

	# --- worker thread ---------------------------------------------------------

	def _put(self, task: _Task) -> concurrent.futures.Future:
		if self._terminated:
			raise RuntimeError("the speech engine has been terminated")
		self._queue.put(task)
		return task.future

	def _is_current(self, generation: int) -> bool:
		return generation == self._generation

	def _run(self) -> None:
		while True:
			task = self._queue.get()
			if task.func is None:
				task.future.set_result(None)
				return
			if task.generation is not None and not self._is_current(task.generation):
				task.future.cancel()
				continue
			try:
				task.future.set_result(task.func())
			except BaseException as e:
				task.future.set_exception(e)
				self._on_error(e)

	def _refresh_sample_rate(self) -> None:
		rate = self._espeak.sample_rate()
		if rate != self._sample_rate:
			self._sample_rate = rate
			self._sink.set_sample_rate(rate)

	def _speak(self, ssml: str, generation: int) -> None:
		samples_done = 0

		def handle(block: AudioBlock) -> bool:
			nonlocal samples_done
			if not self._is_current(generation):
				return False
			marks = [
				(int(e.mark), e.sample)
				for e in block.events
				if e.type == espeakEVENT_MARK and e.mark is not None and e.mark.isdigit()
			]
			for chunk in split_at_marks(len(block.data), samples_done, marks):
				if chunk.index is None and chunk.end == chunk.start:
					continue
				on_done = None
				if chunk.index is not None:
					index = chunk.index
					on_done = lambda: self._report_index(index, generation)  # noqa: E731
				self._sink.feed(block.data[chunk.start : chunk.end], on_done)
				if not self._is_current(generation):
					return False
			samples_done += len(block.data) // 2
			return True

		self._espeak.synth(ssml, handle)
		if self._is_current(generation):
			self._sink.idle()
			if self._is_current(generation):
				self._on_done()
		else:
			# An aborted synthesis can leave SSML prosody changes in effect.
			self._espeak.cancel()
			for parameter, value in self._parameters.items():
				self._espeak.set_parameter(parameter, value)

	def _report_index(self, index: int, generation: int) -> None:
		if self._is_current(generation):
			self._on_index(index)
