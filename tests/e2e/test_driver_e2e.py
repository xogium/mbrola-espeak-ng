"""Full stack: the NVDA SynthDriver with fake NVDA modules but real native libraries.

Covers what NVDA does: construct the driver, list voices, change settings,
speak a speech sequence with index commands, cancel, switch voices,
terminate, and construct it again in the same process (as when the user
switches synthesizers back and forth).

Only nvwave is replaced, by a recording sink. Same environment variables as
test_native_e2e.py.
"""

from __future__ import annotations

import importlib
import os
import shutil
import time
from pathlib import Path

import nvda_fakes
import pytest
from fakes import RecordingSink

pytestmark = pytest.mark.e2e

STAGE = os.environ.get("MBROLA_ESPEAK_STAGE")
VOICES = os.environ.get("MBROLA_TEST_VOICES")
if not STAGE or not VOICES:
	pytest.skip("set MBROLA_ESPEAK_STAGE and MBROLA_TEST_VOICES to run end-to-end tests", allow_module_level=True)


def find_voice(name):
	for candidate in (Path(VOICES) / name, Path(VOICES) / name / name):
		if candidate.is_file():
			return candidate
	return None


def wait_for(predicate, timeout=30.0):
	deadline = time.monotonic() + timeout
	while time.monotonic() < deadline:
		if predicate():
			return True
		time.sleep(0.01)
	return False


@pytest.fixture
def driver(tmp_path, monkeypatch):
	state = nvda_fakes.State()
	state.config_path = str(tmp_path / "config")
	state.ui_language = "en_GB"
	nvda_fakes.install(state)
	module = importlib.import_module("synthDrivers.mbrola_espeak")
	layout_mod = importlib.import_module("synthDrivers.mbrola_espeak.core.layout")
	library_mod = importlib.import_module("synthDrivers.mbrola_espeak.core.voice_library")

	driver_dir = tmp_path / "addon" / "synthDrivers" / "mbrola_espeak"
	shutil.copytree(Path(STAGE) / "bin", driver_dir / "bin")
	shutil.copytree(Path(STAGE) / "espeak-ng-data", driver_dir / "espeak-ng-data")
	layout = layout_mod.AddonLayout.for_nvda(driver_dir, state.config_path)
	monkeypatch.setattr(module, "get_layout", lambda: layout)

	# Import voices the way the settings panel does.
	library = library_mod.VoiceLibrary(layout)
	for name in ("en1", "us1"):
		path = find_voice(name)
		if path:
			library.import_path(path)

	sinks = []

	def make_sink():
		sinks.append(RecordingSink())
		return sinks[-1]

	monkeypatch.setattr(module, "WavePlayerSink", make_sink)
	return module, state, sinks, layout


def test_driver_full_cycle(driver):
	module, state, sinks, layout = driver
	commands = importlib.import_module("speech.commands")
	assert module.SynthDriver.check()

	synth = module.SynthDriver()
	try:
		assert "mb-en1" in synth.availableVoices
		assert synth.voice == "mb-en1"  # en_GB UI -> en-uk voice
		assert sinks[-1].rates[-1] == 16000

		synth.rate = 50
		synth.pitch = 60
		synth.speak(
			[
				"Hello",
				commands.IndexCommand(10),
				" from MBROLA",
				commands.PitchCommand(multiplier=1.3),
				" running in sixty four bits.",
				commands.IndexCommand(11),
			],
		)
		assert wait_for(lambda: state.synthDoneSpeaking.calls)
		assert [c["index"] for c in state.synthIndexReached.calls] == [10, 11]
		assert sinks[-1].total_bytes > 16000  # more than half a second of audio

		if "mb-us1" in synth.availableVoices:
			synth.voice = "mb-us1"
			assert synth.voice == "mb-us1"
			assert synth.rate == 50  # settings survive a voice change

		state.synthDoneSpeaking.calls.clear()
		synth.speak([" ".join(["A long sentence to be cut short."] * 30)])
		synth.cancel()
		synth.speak(["Short."])
		assert wait_for(lambda: state.synthDoneSpeaking.calls)
	finally:
		synth.terminate()

	# NVDA can create the driver again in the same process.
	again = module.SynthDriver()
	try:
		again.speak(["Second life.", commands.IndexCommand(1)])
		assert wait_for(lambda: any(c.get("index") == 1 for c in state.synthIndexReached.calls))
	finally:
		again.terminate()


def test_real_driver_is_freed_when_nvda_switches_synth(driver):
	"""NVDA's Voice panel refreshes only when the old synth object dies (see test_nvda_adapter)."""
	import gc
	import weakref

	module, state, sinks, layout = driver
	commands = importlib.import_module("speech.commands")
	gc.collect()
	gc.disable()
	try:
		synth = module.SynthDriver()
		synth.speak(["Hello", commands.IndexCommand(1)])
		assert wait_for(lambda: state.synthDoneSpeaking.calls)
		ref = weakref.ref(synth)
		synth.terminate()
		del synth
		assert ref() is None
	finally:
		gc.enable()
