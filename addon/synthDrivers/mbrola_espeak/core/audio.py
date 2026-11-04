"""Audio output interface and the index/audio alignment logic.

The engine never talks to a sound device. It hands 16-bit mono PCM to an
:class:`AudioSink`. In NVDA the sink wraps ``nvwave.WavePlayer``
(``_nvda_audio.py``); in tests it records what it received.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Protocol

BYTES_PER_SAMPLE = 2


class AudioSink(Protocol):
	def set_sample_rate(self, rate: int) -> None:
		"""Prepare for audio at ``rate`` Hz. Called before the first ``feed`` and whenever the rate changes."""

	def feed(self, data: bytes, on_done: Callable[[], None] | None = None) -> None:
		"""Queue audio. ``on_done`` runs once this chunk has been played (``data`` may be empty)."""

	def idle(self) -> None:
		"""Block until everything fed so far has been played."""

	def stop(self) -> None:
		"""Drop queued audio immediately. Pending ``on_done`` callbacks are discarded."""

	def pause(self, paused: bool) -> None: ...

	def close(self) -> None: ...


@dataclasses.dataclass(frozen=True)
class Chunk:
	start: int
	end: int
	index: int | None
	"""Index to report once this chunk (and all audio before it) has played."""


def split_at_marks(
	chunk_bytes: int,
	samples_before_chunk: int,
	marks: list[tuple[int, int]],
) -> list[Chunk]:
	"""Split one callback's audio so each index fires when its position is reached.

	:param chunk_bytes: Size of the audio delivered in this callback.
	:param samples_before_chunk: Samples of this utterance delivered by earlier callbacks.
	:param marks: ``(index, sample_position)`` pairs, in order, where ``sample_position``
		is eSpeak NG's ``espeak_EVENT.sample``: a sample count from the start of
		the utterance. Sample counts are used instead of ``audio_position``
		(milliseconds) because eSpeak NG computes the milliseconds with whatever
		sample rate is current when the event is created, which is wrong around
		MBROLA voice changes.
	:returns: Chunks covering ``[0, chunk_bytes)`` in order. Each mark ends a
		chunk; the last chunk has ``index=None`` and may be empty.
	"""
	chunks: list[Chunk] = []
	previous = 0
	for index, sample_position in marks:
		offset = (sample_position - samples_before_chunk) * BYTES_PER_SAMPLE
		# Clamp: positions can fall slightly outside this chunk.
		offset = min(max(offset, previous), chunk_bytes)
		chunks.append(Chunk(previous, offset, index))
		previous = offset
	chunks.append(Chunk(previous, chunk_bytes, None))
	return chunks
