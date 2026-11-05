"""First-run message, download-page link, cross-language voice labels, stripped eSpeak variants."""

import importlib
from pathlib import PurePosixPath

import build_addon
import build_native
import nvda_fakes
import pytest
from core.voice_catalog import MbrolaVoiceDefinition, VoiceCatalog, choose_default
from voice_fixtures import make_voice_bytes


def d(identifier, database, *languages):
	return MbrolaVoiceDefinition(identifier, identifier, database, tuple(languages), None)


CATALOG = VoiceCatalog(
	[
		d("mb-af1-en", "af1", "en"),
		d("mb-af1", "af1", "af"),
		d("mb-en1", "en1", "en-uk", "en"),
		d("mb-fr1", "fr1", "fr-fr", "fr"),
		d("mb-fr1-en", "fr1", "en"),
		d("mb-fr4", "fr4", "fr-fr", "fr"),
		d("mb-fr4-en", "fr4", "en"),
		d("mb-br1", "br1", "pt-br"),
		d("mb-br1-xex", "br1", "xex"),
	],
)


# --- cross-language definitions (why fr1 and fr4 also show English) -------------


def test_home_definition():
	assert CATALOG.home_definition("fr1").identifier == "mb-fr1"
	assert CATALOG.home_definition("zz9") is None


@pytest.mark.parametrize(
	"identifier,expected",
	[("mb-fr1-en", True), ("mb-fr4-en", True), ("mb-af1-en", True), ("mb-fr1", False), ("mb-en1", False)],
)
def test_is_cross_language(identifier, expected):
	assert CATALOG.is_cross_language(CATALOG.by_identifier(identifier)) is expected


def test_default_never_picks_a_cross_language_voice_when_a_native_one_exists():
	defs = list(CATALOG.definitions)
	# mb-af1-en sorts before mb-en1 and is "en", but English users must get mb-en1.
	assert choose_default(defs, "en", CATALOG.is_cross_language).identifier == "mb-en1"
	assert choose_default(defs, "fr_FR", CATALOG.is_cross_language).identifier == "mb-fr1"
	only_cross = [CATALOG.by_identifier("mb-fr1-en"), CATALOG.by_identifier("mb-fr1")]
	assert choose_default(only_cross, "en", CATALOG.is_cross_language).identifier == "mb-fr1-en"


def test_voice_list_labels(tmp_path):
	nvda_fakes.install()
	driver = importlib.import_module("synthDrivers.mbrola_espeak")
	fr1_en = CATALOG.by_identifier("mb-fr1-en")
	fr1 = CATALOG.by_identifier("mb-fr1")
	assert driver.voice_display_name(fr1) == "French (France), MBROLA fr1 (mb-fr1)"
	assert driver.voice_display_name(fr1_en, CATALOG.home_definition("fr1")) == (
		"English, with the French (France) voice fr1 (mb-fr1-en)"
	)


# --- download page -------------------------------------------------------------------


def test_open_voices_page(nvda_plugin):
	links = importlib.import_module("globalPlugins.mbrolaVoiceManager.links")
	opened = []
	assert links.open_voices_page(lambda url: opened.append(url) or True)
	assert opened == ["https://github.com/numediart/MBROLA-voices/tree/master/data"]

	def broken(url):
		raise OSError("no browser")

	assert links.open_voices_page(broken) is False


# --- first-run message ------------------------------------------------------------------


@pytest.fixture
def nvda_plugin(tmp_path, monkeypatch):
	state = nvda_fakes.State()
	state.config_path = str(tmp_path / "config")
	nvda_fakes.install(state)
	driver = importlib.import_module("synthDrivers.mbrola_espeak")
	layout_mod = importlib.import_module("synthDrivers.mbrola_espeak.core.layout")
	layout = layout_mod.AddonLayout.for_nvda(tmp_path / "driver", state.config_path)
	(layout.mbrola_voice_definitions_dir).mkdir(parents=True)
	(layout.mbrola_voice_definitions_dir / "mb-en1").write_text("language en\nmbrola en1 en1_phtrans\n")
	monkeypatch.setattr(driver, "get_layout", lambda: layout)
	plugin_mod = importlib.import_module("globalPlugins.mbrolaVoiceManager")
	links = importlib.import_module("globalPlugins.mbrolaVoiceManager.links")
	opened = []
	monkeypatch.setattr(plugin_mod, "open_voices_page", lambda: opened.append(links.VOICES_DOWNLOAD_URL) or True)
	# Never go online: GitHub has no release, and the check runs on the calling thread.
	update_ui = importlib.import_module("globalPlugins.mbrolaVoiceManager.update_ui")
	monkeypatch.setattr(
		plugin_mod,
		"_make_update_controller",
		lambda: update_ui.UpdateController(
			"mbrolaEspeak",
			"0.2.0",
			tmp_path / "config" / "mbrolaEspeakUpdates.json",
			fetch_json=lambda url: None,
			open_url=None,
			run_in_background=lambda work: work(),
		),
	)
	return state, plugin_mod, layout, opened


def run_deferred(state):
	calls, state.call_after[:] = list(state.call_after), []
	for func, args, kwargs in calls:
		func(*args, **kwargs)


def test_first_run_offers_page_once(nvda_plugin):
	state, plugin_mod, layout, opened = nvda_plugin
	state.message_box_answer = 2  # wx.YES
	plugin_mod.GlobalPlugin()
	run_deferred(state)
	assert len(state.message_boxes) == 1
	assert "No MBROLA voices are installed" in state.message_boxes[0][0]
	assert opened == ["https://github.com/numediart/MBROLA-voices/tree/master/data"]
	# Next NVDA start: not shown again, even though there are still no voices.
	plugin_mod.GlobalPlugin()
	run_deferred(state)
	assert len(state.message_boxes) == 1


def test_first_run_declined_does_not_open_browser(nvda_plugin):
	state, plugin_mod, layout, opened = nvda_plugin
	state.message_box_answer = 8  # wx.NO
	plugin_mod.GlobalPlugin()
	run_deferred(state)
	assert len(state.message_boxes) == 1 and opened == []


def test_no_message_when_voices_already_installed(nvda_plugin):
	state, plugin_mod, layout, opened = nvda_plugin
	layout.voice_store_dir.mkdir(parents=True)
	(layout.voice_store_dir / "en1").write_bytes(make_voice_bytes())
	plugin_mod.GlobalPlugin()
	run_deferred(state)
	assert state.message_boxes == []


def test_no_message_on_secure_screens(nvda_plugin):
	state, plugin_mod, layout, opened = nvda_plugin
	importlib.import_module("globalVars").appArgs.secure = True
	plugin_mod.GlobalPlugin()
	assert state.call_after == []


def test_welcome_marker_does_not_count_as_a_voice(nvda_plugin):
	state, plugin_mod, layout, opened = nvda_plugin
	welcome = importlib.import_module("globalPlugins.mbrolaVoiceManager.welcome")
	welcome.remember_offered(layout.voice_store_dir)
	library = importlib.import_module("synthDrivers.mbrola_espeak.core.voice_library").VoiceLibrary(layout)
	assert library.installed_voices() == []
	assert library.sync().ok


# --- eSpeak NG variants (Alex, Michael, ...) are stripped -----------------------------------


def test_staging_strips_espeak_variants(tmp_path):
	mb = tmp_path / "mb"
	es = tmp_path / "es"
	mb.mkdir()
	(mb / "libmbrola.so").write_bytes(b"m")
	(es / "src").mkdir(parents=True)
	(es / "src" / "libespeak-ng.so.1").write_bytes(b"e")
	data = es / "espeak-ng-data"
	(data / "voices" / "!v").mkdir(parents=True)
	(data / "voices" / "!v" / "Alex").write_text("variant")
	(data / "voices" / "mb").mkdir()
	(data / "voices" / "mb" / "mb-en1").write_text("mbrola en1 x\n")
	(data / "lang").mkdir()
	(data / "lang" / "en").write_text("needed for eSpeak's own language rules")
	build_native.stage_outputs("linux-harness", mb, es, tmp_path / "stage")
	staged = tmp_path / "stage" / "espeak-ng-data"
	assert not (staged / "voices" / "!v").exists()
	assert (staged / "voices" / "mb" / "mb-en1").is_file()
	assert (staged / "lang" / "en").is_file()


def test_package_never_contains_variants():
	rel = PurePosixPath("synthDrivers/mbrola_espeak/espeak-ng-data/voices/!v/Michael")
	assert build_addon.should_include(rel) is False
	assert build_addon.should_include(PurePosixPath("synthDrivers/mbrola_espeak/espeak-ng-data/voices/mb/mb-en1"))
