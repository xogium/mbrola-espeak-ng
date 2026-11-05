"""Tests for the NVDA-facing modules, using fake NVDA modules (tests/nvda_fakes.py)."""

import importlib
import time

import nvda_fakes
import pytest
from fakes import FakeEspeak, RecordingSink
from voice_fixtures import make_voice_bytes, write_definitions


@pytest.fixture
def nvda(tmp_path):
	state = nvda_fakes.State()
	state.config_path = str(tmp_path / "config")
	return nvda_fakes.install(state)


@pytest.fixture
def driver_module(nvda, tmp_path, monkeypatch):
	module = importlib.import_module("synthDrivers.mbrola_espeak")
	layout_mod = importlib.import_module("synthDrivers.mbrola_espeak.core.layout")
	driver_dir = tmp_path / "driver"
	(driver_dir / "bin").mkdir(parents=True)
	layout = layout_mod.AddonLayout(
		driver_dir=driver_dir,
		voice_store_dir=tmp_path / "config" / "mbrolaVoices",
		espeak_library_name="espeak.dll",
		mbrola_library_name="mbrola.dll",
	)
	(driver_dir / "bin" / "espeak.dll").write_bytes(b"")
	(driver_dir / "bin" / "mbrola.dll").write_bytes(b"")
	write_definitions(layout.mbrola_voice_definitions_dir, {"mb-en1": "en1", "mb-us1": "us1", "mb-de6": "de6"})
	# Give the voices real language lines.
	(layout.mbrola_voice_definitions_dir / "mb-en1").write_text("name english-mb-en1\nlanguage en-uk 3\nmbrola en1 x\n")
	(layout.mbrola_voice_definitions_dir / "mb-us1").write_text("name us-mbrola-1\nlanguage en-us\nmbrola us1 x\n")
	monkeypatch.setattr(module, "get_layout", lambda: layout)
	espeak = FakeEspeak()
	espeak.voice_rates = {"mb-en1": 16000, "mb-us1": 16000}
	sink = RecordingSink()
	monkeypatch.setattr(module, "EspeakBinding", lambda *args: espeak)
	monkeypatch.setattr(module, "WavePlayerSink", lambda: sink)
	module._test = type("T", (), {"layout": layout, "espeak": espeak, "sink": sink})
	return module


def install_voice(layout, name):
	layout.voice_store_dir.mkdir(parents=True, exist_ok=True)
	(layout.voice_store_dir / name).write_bytes(make_voice_bytes())


def wait_for(predicate, timeout=5.0):
	deadline = time.monotonic() + timeout
	while time.monotonic() < deadline:
		if predicate():
			return True
		time.sleep(0.01)
	return False


# --- driver -----------------------------------------------------------------


def test_check_reports_incomplete_install(driver_module):
	assert driver_module.SynthDriver.check()
	(driver_module._test.layout.bin_dir / "mbrola.dll").unlink()
	assert not driver_module.SynthDriver.check()


def test_init_without_voices_fails_with_helpful_message(driver_module):
	errors = importlib.import_module("synthDrivers.mbrola_espeak.core.errors")
	with pytest.raises(errors.MbrolaEspeakError, match="Import one in NVDA Settings"):
		driver_module.SynthDriver()


def test_lists_only_installed_voices_and_picks_ui_language(driver_module, nvda):
	install_voice(driver_module._test.layout, "en1")
	install_voice(driver_module._test.layout, "us1")
	synth = driver_module.SynthDriver()
	try:
		assert list(synth.availableVoices) == ["mb-en1", "mb-us1"]
		assert synth.availableVoices["mb-en1"].displayName == "English (UK), MBROLA en1 (mb-en1)"
		assert synth.availableVoices["mb-us1"].language == "en-us"
		# nvda.ui_language is en_US.
		assert synth.voice == "mb-us1"
		# Voices were mirrored to where eSpeak NG looks.
		assert (driver_module._test.layout.espeak_mbrola_dir / "en1").is_file()
	finally:
		synth.terminate()


def test_settings_map_to_espeak_parameters(driver_module):
	install_voice(driver_module._test.layout, "en1")
	synth = driver_module.SynthDriver()
	try:
		assert (synth.rate, synth.pitch, synth.inflection, synth.volume) == (30, 40, 75, 100)
		synth.rate = 100
		assert synth.rate == 100
		synth._engine.wait_until_idle(5)
		assert ("set_parameter", 1, 450) in driver_module._test.espeak.calls
	finally:
		synth.terminate()


def test_unknown_voice_is_ignored(driver_module, nvda):
	install_voice(driver_module._test.layout, "en1")
	synth = driver_module.SynthDriver()
	try:
		synth.voice = "mb-de6"  # definition exists, database not installed
		assert synth.voice == "mb-en1"
		assert any("ignoring unknown voice" in msg for _, msg in nvda.log.records)
	finally:
		synth.terminate()


def test_speak_produces_index_and_done_notifications(driver_module, nvda):
	install_voice(driver_module._test.layout, "en1")
	commands = importlib.import_module("speech.commands")
	synth = driver_module.SynthDriver()
	try:
		synth.speak(["Hello", commands.IndexCommand(1), " world", commands.IndexCommand(2)])
		assert wait_for(lambda: nvda.synthDoneSpeaking.calls)
		assert [c["index"] for c in nvda.synthIndexReached.calls] == [1, 2]
		assert all(c["synth"] is synth for c in nvda.synthIndexReached.calls)
		ssml = [c for c in driver_module._test.espeak.calls if c[0] == "synth"][-1][1]
		assert ssml == 'Hello<mark name="1"/> world<mark name="2"/>'
	finally:
		synth.terminate()


def test_cancel_and_pause_reach_the_sink(driver_module):
	install_voice(driver_module._test.layout, "en1")
	synth = driver_module.SynthDriver()
	try:
		synth.pause(True)
		synth.cancel()
		assert ("pause", True) in driver_module._test.sink.events
		assert ("stop",) in driver_module._test.sink.events
	finally:
		synth.terminate()


def test_lang_change_is_not_advertised(driver_module):
	commands = importlib.import_module("speech.commands")
	assert commands.LangChangeCommand not in driver_module.SynthDriver.supportedCommands
	assert commands.IndexCommand in driver_module.SynthDriver.supportedCommands


# --- command conversion -------------------------------------------------------


def test_command_conversion(nvda):
	conv = importlib.import_module("synthDrivers.mbrola_espeak._nvda_commands")
	items_mod = importlib.import_module("synthDrivers.mbrola_espeak.core.speech_items")
	c = importlib.import_module("speech.commands")
	unknown = []
	items = conv.to_speech_items(
		[
			"text",
			c.IndexCommand(3),
			c.CharacterModeCommand(True),
			c.BreakCommand(time=100),
			c.PitchCommand(multiplier=1.5),
			c.RateCommand(multiplier=0.5),
			c.VolumeCommand(multiplier=2),
			c.PhonemeCommand("θ", text="th"),
			c.PhonemeCommand("θ"),
			c.LangChangeCommand("fr"),
			object(),
		],
		on_unknown=unknown.append,
	)
	assert items == [
		items_mod.Text("text"),
		items_mod.Index(3),
		items_mod.CharacterMode(True),
		items_mod.Break(100),
		items_mod.Prosody("pitch", 1.5),
		items_mod.Prosody("rate", 0.5),
		items_mod.Prosody("volume", 2),
		items_mod.Text("th"),
	]
	assert len(unknown) == 1


# --- audio adapter --------------------------------------------------------------


class FakePlayer:
	def __init__(self, rate):
		self.rate = rate
		self.calls = []

	def feed(self, data, onDone=None):
		self.calls.append(("feed", data, onDone))

	def idle(self):
		self.calls.append(("idle",))

	def stop(self):
		self.calls.append(("stop",))

	def pause(self, switch):
		self.calls.append(("pause", switch))

	def close(self):
		self.calls.append(("close",))


def test_wave_player_sink(nvda):
	audio = importlib.import_module("synthDrivers.mbrola_espeak._nvda_audio")
	players = []

	def factory(rate):
		players.append(FakePlayer(rate))
		return players[-1]

	sink = audio.WavePlayerSink(factory)
	sink.stop()  # no player yet: must not fail
	sink.set_sample_rate(22050)
	sink.set_sample_rate(22050)  # same rate: player kept
	assert len(players) == 1
	sink.set_sample_rate(16000)
	assert [p.rate for p in players] == [22050, 16000]
	assert ("close",) in players[0].calls
	done = object()
	sink.feed(b"ab", done)
	sink.idle()
	sink.pause(True)
	sink.stop()
	sink.close()
	assert players[1].calls == [("feed", b"ab", done), ("idle",), ("pause", True), ("stop",), ("close",)]
	sink.feed(b"x")  # after close: ignored


# --- settings panel presenter -------------------------------------------------------


@pytest.fixture
def presenter(nvda, tmp_path):
	layout_mod = importlib.import_module("synthDrivers.mbrola_espeak.core.layout")
	library_mod = importlib.import_module("synthDrivers.mbrola_espeak.core.voice_library")
	errors = importlib.import_module("synthDrivers.mbrola_espeak.core.errors")
	presenter_mod = importlib.import_module("globalPlugins.mbrolaVoiceManager.presenter")
	layout = layout_mod.AddonLayout(driver_dir=tmp_path / "driver", voice_store_dir=tmp_path / "store")
	write_definitions(layout.mbrola_voice_definitions_dir, {"mb-en1": "en1", "mb-br1": "br1", "mb-br1-xex": "br1"})
	library = library_mod.VoiceLibrary(layout)
	return presenter_mod.VoiceManagerPresenter(library, expected_errors=(errors.MbrolaEspeakError,)), tmp_path


def test_presenter_import_list_and_remove(presenter):
	p, tmp = presenter
	(tmp / "br1").write_bytes(make_voice_bytes(rate=16000))
	outcome = p.import_files([tmp / "br1"])
	assert outcome.message == "Imported: br1."
	assert not outcome.is_error and outcome.voices_changed
	[entry] = p.entries()
	assert entry.name == "br1"
	assert entry.label == "br1, 16000 Hz, voices: mb-br1, mb-br1-xex"
	outcome = p.remove("br1")
	assert outcome.message == "br1 was removed." and outcome.voices_changed
	assert p.entries() == []


def test_presenter_reports_bad_files_and_keeps_going(presenter):
	p, tmp = presenter
	(tmp / "en1").write_bytes(make_voice_bytes())
	(tmp / "junk").write_bytes(b"nope")
	outcome = p.import_files([tmp / "junk", tmp / "en1"])
	assert outcome.message.startswith("Imported: en1. Problems: junk:")
	assert not outcome.is_error


def test_presenter_nothing_imported_is_an_error(presenter):
	p, tmp = presenter
	(tmp / "en1").write_bytes(b"<html>")
	outcome = p.import_files([tmp / "en1"])
	assert outcome.is_error and not outcome.voices_changed
	assert "not an MBROLA voice" in outcome.message


def test_global_plugin_registers_and_unregisters_panel(nvda):
	plugin_mod = importlib.import_module("globalPlugins.mbrolaVoiceManager")
	nvda.NVDASettingsDialog.categoryClasses.clear()
	plugin = plugin_mod.GlobalPlugin()
	assert nvda.NVDASettingsDialog.categoryClasses == [plugin_mod.MbrolaVoicesPanel]
	plugin.terminate()
	plugin.terminate()
	assert nvda.NVDASettingsDialog.categoryClasses == []


def test_presenter_imports_a_whole_folder(presenter):
	p, tmp = presenter
	folder = tmp / "voices"
	for name in ("en1", "br1"):
		(folder / "data" / name).mkdir(parents=True)
		(folder / "data" / name / name).write_bytes(make_voice_bytes())
	outcome = p.import_files([folder])
	assert outcome.message == "Imported: br1, en1."
	assert [e.name for e in p.entries()] == ["br1", "en1"]


def test_presenter_reports_folder_without_voices(presenter):
	p, tmp = presenter
	(tmp / "nothing").mkdir()
	outcome = p.import_files([tmp / "nothing"])
	assert outcome.is_error and "No MBROLA voices" in outcome.message


def test_panel_instructions_are_the_accessible_description(nvda):
	"""The instructions must be the panel's description (spoken and brailled by NVDA), not just loose text."""
	panel_mod = importlib.import_module("globalPlugins.mbrolaVoiceManager.panel")
	description = panel_mod.MbrolaVoicesPanel.panelDescription
	assert "github.com/numediart/MBROLA-voices" in description
	assert "folder" in description
