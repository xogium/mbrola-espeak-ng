import threading

import pytest
from fakes import FakeEspeak, RecordingSink

from core.engine import SpeechEngine
from core.params import EspeakParameter


class Harness:
	def __init__(self, espeak=None, sink=None):
		self.espeak = espeak or FakeEspeak()
		self.sink = sink or RecordingSink()
		self.indexes = []
		self.done = threading.Event()
		self.done_count = 0
		self.errors = []
		self.engine = SpeechEngine(self.espeak, self.sink, self._on_index, self._on_done, self.errors.append)

	def _on_index(self, i):
		self.indexes.append(i)

	def _on_done(self):
		self.done_count += 1
		self.done.set()


@pytest.fixture
def h():
	harness = Harness()
	yield harness
	harness.engine.terminate()


def test_initial_sample_rate_is_given_to_sink(h):
	assert h.sink.rates == [22050]
	assert h.engine.sample_rate == 22050


def test_speak_reports_indexes_in_order_then_done(h):
	h.engine.speak("hello").result(5)
	assert h.indexes == [1, 2]
	assert h.done_count == 1
	# 200 samples of audio, all fed.
	assert h.sink.total_bytes == 400
	assert ("idle",) in h.sink.events


def test_audio_is_split_exactly_at_marks(h):
	h.engine.speak("x").result(5)
	# Block 1: 100 samples, mark at sample 50 -> 100 bytes, then 100 bytes.
	# Block 2: starts at sample 100, mark at 150 -> 100 bytes, then 100 bytes.
	assert [len(d) for d in h.sink.fed] == [100, 100, 100, 100]


def test_index_fires_only_after_its_audio_played():
	sink = RecordingSink(play_immediately=False)
	h = Harness(sink=sink)
	try:
		h.engine.speak("x").result(5)
		assert h.indexes == []
		sink.play_pending()
		assert h.indexes == [1, 2]
	finally:
		h.engine.terminate()


def test_voice_change_updates_rate_and_reapplies_parameters(h):
	h.espeak.voice_rates["mb-en1"] = 16000
	h.engine.set_parameter(EspeakParameter.RATE, 200)
	h.engine.set_voice("mb-en1").result(5)
	assert h.engine.voice == "mb-en1"
	assert h.sink.rates == [22050, 16000]
	calls = h.espeak.calls
	assert calls.index(("set_voice", "mb-en1")) < calls.index(("set_parameter", 1, 200), 1)


def test_failed_voice_change_raises_through_future(h):
	h.espeak.fail_voice.add("mb-zz9")
	with pytest.raises(RuntimeError):
		h.engine.set_voice("mb-zz9").result(5)
	assert h.engine.voice is None
	assert len(h.errors) == 1


def test_parameters_are_cached_for_getters(h):
	assert h.engine.get_parameter(EspeakParameter.PITCH) is None
	h.engine.set_parameter(EspeakParameter.PITCH, 42)
	assert h.engine.get_parameter(EspeakParameter.PITCH) == 42


def test_cancel_aborts_current_utterance_and_skips_queued_ones():
	espeak = FakeEspeak()
	espeak.gate = threading.Event()
	h = Harness(espeak=espeak)
	try:
		first = h.engine.speak("first")
		queued = h.engine.speak("second")
		assert espeak.first_block_sent.wait(5)
		h.engine.cancel()
		h.engine.set_parameter(EspeakParameter.VOLUME, 50)  # must survive the cancel
		espeak.gate.set()
		first.result(5)
		h.engine.wait_until_idle(5)
		assert queued.cancelled()
		synths = [c for c in espeak.calls if c[0] == "synth"]
		assert synths == [("synth", "first")]
		assert ("aborted", "first") in espeak.calls
		# After an abort the engine resets eSpeak and re-applies parameters.
		assert ("cancel",) in espeak.calls
		assert ("set_parameter", 2, 50) in espeak.calls
		assert h.done_count == 0
		assert ("stop",) in h.sink.events
		# Index 2 belongs to audio after the cancel and must never be reported.
		assert 2 not in h.indexes
	finally:
		h.engine.terminate()


def test_speech_after_cancel_works(h):
	h.engine.cancel()
	h.engine.speak("again").result(5)
	assert h.done_count == 1


def test_stale_index_callbacks_are_dropped():
	sink = RecordingSink(play_immediately=False)
	h = Harness(sink=sink)
	try:
		h.engine.speak("x").result(5)
		pending = list(sink.pending)
		h.engine.cancel()
		for cb in pending:
			cb()
		assert h.indexes == []
	finally:
		h.engine.terminate()


def test_errors_in_tasks_are_reported_and_worker_survives(h):
	def broken():
		raise ValueError("boom")

	with pytest.raises(ValueError):
		h.engine.submit(broken).result(5)
	assert isinstance(h.errors[0], ValueError)
	h.engine.speak("still alive").result(5)
	assert h.done_count == 1


def test_pause_is_forwarded(h):
	h.engine.pause(True)
	h.engine.pause(False)
	assert ("pause", True) in h.sink.events and ("pause", False) in h.sink.events


def test_terminate_is_idempotent_and_closes_everything():
	h = Harness()
	h.engine.terminate()
	h.engine.terminate()
	assert ("terminate",) in h.espeak.calls
	assert h.sink.closed
	with pytest.raises(RuntimeError):
		h.engine.speak("too late")
