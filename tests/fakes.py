"""Test doubles for the engine's two interfaces: EspeakLike and AudioSink."""

from __future__ import annotations

import threading

from core.espeak_binding import AudioBlock, SynthEvent, espeakEVENT_MARK


class FakeEspeak:
	"""Plays back a script of blocks for every synth() call.

	Each script entry is ``(samples, [(index, sample_position), ...])``.
	If ``gate`` is set, synthesis waits on it after the first block, so tests
	can cancel in the middle.
	"""

	def __init__(self, script=None, rate=22050):
		self.script = script if script is not None else [(100, [(1, 50)]), (100, [(2, 150)])]
		self.rate = rate
		self.voice_rates = {}
		self.calls = []
		self.gate: threading.Event | None = None
		self.first_block_sent = threading.Event()
		self.fail_voice = set()

	def sample_rate(self):
		return self.rate

	def version(self):
		return "1.52.0-fake"

	def set_voice(self, identifier):
		self.calls.append(("set_voice", identifier))
		if identifier in self.fail_voice:
			raise RuntimeError(f"no voice {identifier}")
		self.rate = self.voice_rates.get(identifier, self.rate)

	def set_parameter(self, parameter, value):
		self.calls.append(("set_parameter", int(parameter), value))

	def synth(self, ssml, handler):
		self.calls.append(("synth", ssml))
		for i, (samples, marks) in enumerate(self.script):
			events = tuple(SynthEvent(espeakEVENT_MARK, 0, pos, mark=str(idx)) for idx, pos in marks)
			if not handler(AudioBlock(data=b"\x01\x00" * samples, events=events)):
				self.calls.append(("aborted", ssml))
				return 0
			if i == 0:
				self.first_block_sent.set()
				if self.gate is not None:
					self.gate.wait(5)
		handler(AudioBlock(data=b"", events=()))
		return 0

	def cancel(self):
		self.calls.append(("cancel",))

	def terminate(self):
		self.calls.append(("terminate",))


class RecordingSink:
	def __init__(self, play_immediately=True):
		self.play_immediately = play_immediately
		self.rates = []
		self.fed = []
		self.pending = []
		self.events = []
		self.closed = False

	def set_sample_rate(self, rate):
		self.rates.append(rate)
		self.events.append(("rate", rate))

	def feed(self, data, on_done=None):
		self.fed.append(data)
		self.events.append(("feed", len(data)))
		if on_done is not None:
			if self.play_immediately:
				on_done()
			else:
				self.pending.append(on_done)

	def play_pending(self):
		pending, self.pending = self.pending, []
		for cb in pending:
			cb()

	def idle(self):
		self.events.append(("idle",))

	def stop(self):
		self.pending = []
		self.events.append(("stop",))

	def pause(self, paused):
		self.events.append(("pause", paused))

	def close(self):
		self.closed = True

	@property
	def total_bytes(self):
		return sum(len(d) for d in self.fed)
