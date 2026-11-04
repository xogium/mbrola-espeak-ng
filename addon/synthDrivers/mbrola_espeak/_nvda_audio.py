"""The core's AudioSink, implemented on top of NVDA's ``nvwave.WavePlayer``."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

PlayerFactory = Callable[[int], Any]


def default_player_factory(sample_rate: int):
	import config
	import nvwave

	# Same arguments as NVDA 2026.3's built-in eSpeak driver.
	return nvwave.WavePlayer(
		channels=1,
		samplesPerSec=sample_rate,
		bitsPerSample=16,
		outputDevice=config.conf["audio"]["outputDevice"],
	)


class WavePlayerSink:
	"""Owns one WavePlayer, and replaces it when the sample rate changes.

	``set_sample_rate`` and ``feed`` are called on the engine's worker thread.
	``stop`` and ``pause`` come from NVDA's main thread. A lock keeps the
	player swap atomic.
	"""

	def __init__(self, player_factory: PlayerFactory = default_player_factory):
		self._factory = player_factory
		self._player = None
		self._rate = 0
		self._lock = threading.Lock()

	def set_sample_rate(self, rate: int) -> None:
		with self._lock:
			if rate == self._rate and self._player is not None:
				return
			old, self._player, self._rate = self._player, self._factory(rate), rate
		if old is not None:
			old.close()

	def _current(self):
		with self._lock:
			return self._player

	def feed(self, data: bytes, on_done: Callable[[], None] | None = None) -> None:
		player = self._current()
		if player is not None:
			player.feed(data, onDone=on_done)

	def idle(self) -> None:
		player = self._current()
		if player is not None:
			player.idle()

	def stop(self) -> None:
		player = self._current()
		if player is not None:
			player.stop()

	def pause(self, paused: bool) -> None:
		player = self._current()
		if player is not None:
			player.pause(paused)

	def close(self) -> None:
		with self._lock:
			player, self._player, self._rate = self._player, None, 0
		if player is not None:
			player.close()
