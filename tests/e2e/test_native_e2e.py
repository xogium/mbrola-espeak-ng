"""End-to-end tests against the real native libraries and real MBROLA voices.

Needs:
  MBROLA_ESPEAK_STAGE  output of `tools/build_native.py --target linux-harness`
                       (folder with bin/ and espeak-ng-data/)
  MBROLA_TEST_VOICES   folder containing real voices, either flat (en1, us1)
                       or as in the MBROLA-voices repo (en1/en1, us1/us1).
                       en1 is required; us1 is used when present.

These run the same Python code (binding, engine, voice library) and the same
patched C sources as the add-on in NVDA. Only the platform loader differs:
dlopen instead of LoadLibrary.
"""

from __future__ import annotations

import array
import os
import shutil
import threading
from pathlib import Path

import pytest
from core.engine import SpeechEngine
from core.errors import NativeLibraryError
from core.espeak_binding import EspeakBinding
from core.layout import AddonLayout
from core.params import PITCH, RATE, EspeakParameter
from core.speech_items import Index, Prosody, Text
from core.ssml import build_ssml
from core.voice_file import read_header_from_path
from core.voice_library import VoiceLibrary
from fakes import RecordingSink

pytestmark = pytest.mark.e2e

STAGE = os.environ.get("MBROLA_ESPEAK_STAGE")
VOICES = os.environ.get("MBROLA_TEST_VOICES")

if not STAGE or not VOICES:
	pytest.skip("set MBROLA_ESPEAK_STAGE and MBROLA_TEST_VOICES to run end-to-end tests", allow_module_level=True)


def find_voice(name: str) -> Path | None:
	for candidate in (Path(VOICES) / name, Path(VOICES) / name / name):
		if candidate.is_file():
			return candidate
	return None


@pytest.fixture(scope="session")
def layout(tmp_path_factory) -> AddonLayout:
	# Work on a copy so the tests never modify the build output.
	driver_dir = tmp_path_factory.mktemp("driver")
	shutil.copytree(Path(STAGE) / "bin", driver_dir / "bin")
	shutil.copytree(Path(STAGE) / "espeak-ng-data", driver_dir / "espeak-ng-data")
	return AddonLayout(driver_dir=driver_dir, voice_store_dir=tmp_path_factory.mktemp("store"))


@pytest.fixture(scope="session")
def library(layout) -> VoiceLibrary:
	lib = VoiceLibrary(layout)
	en1 = find_voice("en1")
	assert en1 is not None, "the en1 voice is required for end-to-end tests"
	for name in ("en1", "us1", "fr1"):
		path = find_voice(name)
		if path:
			lib.import_path(path)
	report = lib.sync()
	assert report.ok, report.failed
	return lib


@pytest.fixture(scope="session")
def binding(layout, library) -> EspeakBinding:
	b = EspeakBinding(layout.espeak_library, layout.mbrola_library, layout.espeak_home)
	yield b
	b.terminate()


class KeepAlive:
	"""Lets an engine be terminated without terminating the shared eSpeak NG instance."""

	def __init__(self, inner):
		self._inner = inner

	def __getattr__(self, name):
		return getattr(self._inner, name)

	def terminate(self):
		pass


def synth_all(binding: EspeakBinding, text: str) -> bytes:
	blocks = []
	rc = binding.synth(text, lambda block: blocks.append(block.data) or True)
	assert rc == 0
	return b"".join(blocks)


def peak(pcm: bytes) -> int:
	samples = array.array("h", pcm)
	return max((abs(s) for s in samples), default=0)


def median_pitch_hz(pcm: bytes, rate: int) -> float:
	"""Rough fundamental frequency of the voiced parts of ``pcm`` (autocorrelation, median over frames)."""
	samples = array.array("h", pcm[: len(pcm) // 2 * 2])
	frame, hop = rate // 25, rate // 50
	shortest, longest = rate // 400, rate // 60
	estimates = []
	for start in range(0, len(samples) - frame - longest, hop):
		window = samples[start : start + frame + longest]
		energy = sum(v * v for v in window[:frame])
		if energy < frame * 300**2:
			continue  # silence
		best, best_lag = 0, 0
		for lag in range(shortest, longest):
			c = sum(window[i] * window[i + lag] for i in range(0, frame, 2))
			if c > best:
				best, best_lag = c, lag
		if best_lag and best > energy / 4:
			estimates.append(rate / best_lag)
	assert estimates, "no voiced audio"
	estimates.sort()
	return estimates[len(estimates) // 2]


# --- voices and catalog ---------------------------------------------------------


def test_real_voice_headers(library):
	voices = library.installed_voices()
	assert "en1" in {v.name for v in voices}
	for v in voices:
		header = read_header_from_path(v.path)
		assert header.sample_rate == 16000
		assert header.diphone_count > 1000


def test_catalog_covers_installed_voices(library):
	speakable = {d.identifier for d in library.speakable_definitions()}
	assert "mb-en1" in speakable
	# eSpeak NG 1.52.0 ships about 90 MBROLA voice definitions.
	assert len(library.catalog.definitions) > 80


def test_sync_put_voices_where_espeak_looks(layout, library):
	for v in library.installed_voices():
		assert (layout.espeak_mbrola_dir / v.name).is_file()


# --- binding ----------------------------------------------------------------------


def test_version(binding):
	assert binding.version().startswith("1.52")


def test_every_installed_mbrola_voice_speaks(binding, library):
	for definition in library.speakable_definitions():
		binding.set_voice(definition.identifier)
		assert binding.sample_rate() == 16000, definition.identifier
		pcm = synth_all(binding, "Testing one two three.")
		seconds = len(pcm) / 2 / 16000
		assert 0.5 < seconds < 5, (definition.identifier, seconds)
		assert peak(pcm) > 1000, definition.identifier


def test_cross_language_definitions_speak(binding, library):
	"""mb-fr1-en is eSpeak NG's 'English text read by the French voice fr1'."""
	if "fr1" not in library.store.installed_names():
		pytest.skip("fr1 voice not available")
	assert library.catalog.is_cross_language(library.catalog.by_identifier("mb-fr1-en"))
	for identifier in ("mb-fr1", "mb-fr1-en"):
		binding.set_voice(identifier)
		assert peak(synth_all(binding, "Bonjour, hello.")) > 1000, identifier


def test_uninstalled_mbrola_voice_is_an_error(binding, library):
	missing = next(d for d in library.catalog.definitions if d.database not in library.store.installed_names())
	with pytest.raises(NativeLibraryError):
		binding.set_voice(missing.identifier)


def test_native_rate_is_restored_after_mbrola(binding):
	"""Regression test for native/patches/espeak-ng/0001."""
	binding.set_voice("mb-en1")
	assert binding.sample_rate() == 16000
	binding.set_voice("en")
	assert binding.sample_rate() == 22050


@pytest.mark.parametrize("voice", ["mb-en1", "mb-us1", "en"])
def test_prosody_pitch_reaches_the_voice(binding, library, voice):
	"""Regression test for native/patches/espeak-ng/0002.

	NVDA raises the pitch of capital letters with a PitchCommand, which the
	driver sends as <prosody pitch="...%">. Unpatched eSpeak NG applied it
	after MBROLA had already been given the phonemes, so capitals sounded
	exactly like lower-case letters with MBROLA voices.
	"""
	if voice.startswith("mb-") and voice[3:] not in library.store.installed_names():
		pytest.skip(f"{voice[3:]} voice not available")
	binding.set_voice(voice)
	binding.set_parameter(EspeakParameter.PITCH, PITCH.from_percent(40))
	rate = binding.sample_rate()

	def pitch_of(*items):
		return median_pitch_hz(synth_all(binding, build_ssml(items)), rate)

	normal = pitch_of(Text("A"))
	# What NVDA sends for a capital at pitch 40 with "capital pitch change" 30: 70 / 40.
	capital = pitch_of(Prosody("pitch", 1.75), Text("A"), Prosody("pitch", 1.0))
	afterwards = pitch_of(Text("A"))
	assert capital > normal * 1.15, (normal, capital)
	# The raised pitch must not leak into the next utterance.
	assert abs(afterwards - normal) < normal * 0.05, (normal, afterwards)


def test_switching_voices_repeatedly_does_not_crash(binding, library):
	"""Regression test for native/patches/mbrola/0002 (crash and leak on voice switch)."""
	voices = [d.identifier for d in library.speakable_definitions()] + ["en"]
	for i in range(30):
		v = voices[i % len(voices)]
		binding.set_voice(v)
		assert len(synth_all(binding, "ok")) > 0


def test_marks_arrive_with_increasing_sample_positions(binding):
	binding.set_voice("mb-en1")
	marks = []

	def handler(block):
		marks.extend((e.mark, e.sample) for e in block.events if e.mark)
		return True

	binding.synth('one <mark name="1"/>two <mark name="2"/>three <mark name="3"/>', handler)
	assert [m for m, _ in marks] == ["1", "2", "3"]
	positions = [s for _, s in marks]
	assert positions == sorted(positions) and positions[0] > 0


# --- engine -----------------------------------------------------------------------


@pytest.fixture
def engine_harness(binding):
	sink = RecordingSink()
	indexes = []
	done = threading.Event()
	errors = []
	engine = SpeechEngine(KeepAlive(binding), sink, indexes.append, done.set, errors.append)
	engine.set_voice("mb-en1").result(10)
	engine.set_parameter(EspeakParameter.RATE, RATE.from_percent(30)).result(10)
	yield engine, sink, indexes, done, errors
	engine.terminate()


def test_engine_speaks_with_indexes(engine_harness):
	engine, sink, indexes, done, errors = engine_harness
	ssml = build_ssml([Text("Hello"), Index(1), Text(" world, this is"), Index(2), Text(" MBROLA.")])
	engine.speak(ssml).result(30)
	assert done.is_set()
	assert indexes == [1, 2]
	assert sink.rates[-1] == 16000
	assert peak(b"".join(sink.fed)) > 1000
	assert errors == []


def test_engine_cancel_with_real_library(engine_harness):
	engine, sink, indexes, done, errors = engine_harness
	first_feed = threading.Event()
	cancelled = threading.Event()
	original_feed = sink.feed

	def feed(data, on_done=None):
		original_feed(data, on_done)
		first_feed.set()
		# Like a real sound card, hold the synthesis thread until the cancel has happened.
		cancelled.wait(10)

	sink.feed = feed
	long_text = " ".join(["This is a long sentence that will be interrupted."] * 20)
	future = engine.speak(build_ssml([Text(long_text), Index(99)]))
	assert first_feed.wait(10)
	engine.cancel()
	cancelled.set()
	future.result(30)
	assert not done.is_set()
	assert 99 not in indexes
	# Spoken audio is far shorter than the full text would be.
	assert sink.total_bytes / 2 / 16000 < 20
	# And the engine still works afterwards.
	engine.speak(build_ssml([Text("Back again.")])).result(30)
	assert done.is_set()
	assert errors == []


_LEAK_PROBE = r"""
import ctypes, os, resource, sys
lib = ctypes.CDLL(sys.argv[1])
lib.init_MBR.argtypes = [ctypes.c_char_p]
voice = sys.argv[2].encode()
def fds():
    n = 0
    for fd in range(4096):
        try:
            os.fstat(fd); n += 1
        except OSError:
            pass
    return n
assert lib.init_MBR(voice) == 0
rss0, fds0 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, fds()
for _ in range(50):
    assert lib.init_MBR(voice) == 0
lib.close_MBR(); lib.close_MBR()  # closing twice must be safe
rss1, fds1 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, fds()
print(rss1 - rss0, fds1 - fds0)
"""


@pytest.mark.skipif(os.name != "posix", reason="uses resource and POSIX file descriptors")
def test_voice_reload_leaks_neither_memory_nor_file_handles(layout, library):
	"""Regression test for native/patches/mbrola/0002.

	Unpatched MBROLA keeps every previously loaded voice: about 80 KB and one
	open file handle per voice switch (the handle also locks the voice file on
	Windows, so it could not be removed or updated).
	"""
	import subprocess
	import sys

	voice = layout.espeak_mbrola_dir / "en1"
	result = subprocess.run(
		[sys.executable, "-I", "-c", _LEAK_PROBE, str(layout.mbrola_library), str(voice)],
		capture_output=True,
		text=True,
		check=True,
	)
	rss_growth_kb, fd_growth = (int(x) for x in result.stdout.split())
	assert fd_growth <= 0, f"{fd_growth} file handles leaked over 50 voice loads"
	assert rss_growth_kb < 1024, f"memory grew by {rss_growth_kb} KB over 50 voice loads"
