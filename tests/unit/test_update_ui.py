"""The NVDA side of updates (update_ui.py) and its wiring, with fake NVDA modules and a fake GitHub."""

import importlib

import nvda_fakes
import pytest
from update_fixtures import FakeGitHub, make_package, release_json

YES, NO = 2, 8  # wx.YES, wx.NO in the fakes
DAY = 24 * 60 * 60


class Clock:
	def __init__(self, now=100 * DAY):
		self.now = now

	def __call__(self):
		return self.now


@pytest.fixture
def nvda(tmp_path):
	state = nvda_fakes.State()
	state.config_path = str(tmp_path / "config")
	return nvda_fakes.install(state)


@pytest.fixture
def make_controller(nvda, tmp_path):
	update_ui = importlib.import_module("globalPlugins.mbrolaVoiceManager.update_ui")

	def make(github, clock=None, version="0.2.0"):
		return update_ui.UpdateController(
			"mbrolaEspeak",
			version,
			tmp_path / "config" / "mbrolaEspeakUpdates.json",
			fetch_json=github.fetch_json,
			open_url=github.open_url,
			run_in_background=lambda work: work(),  # no threads in tests
			clock=clock or Clock(),
		)

	return make


def drain(state):
	"""Run what was queued with wx.CallAfter, including what that queues in turn."""
	while state.call_after:
		func, args, kwargs = state.call_after.pop(0)
		func(*args, **kwargs)


def newer_release():
	package = make_package(version="0.3.0")
	return FakeGitHub(release_json("v0.3.0", package=package), package), package


# --- checking by hand ----------------------------------------------------------------------


def test_manual_check_up_to_date(nvda, make_controller):
	make_controller(FakeGitHub(release_json("v0.2.0"))).check_now()
	drain(nvda)
	[(message, title, style)] = nvda.message_boxes
	assert message == "You have the latest version of the eSpeak NG with MBROLA add-on (0.2.0)."
	assert title == "MBROLA add-on update"


def test_manual_check_failure_is_reported(nvda, make_controller):
	make_controller(FakeGitHub({"tag_name": "v0.3.0", "assets": []})).check_now()
	drain(nvda)
	[(message, _, _)] = nvda.message_boxes
	assert message.startswith("Could not check for MBROLA add-on updates. The new release does not contain")


def test_accepting_an_update_downloads_and_installs_it(nvda, make_controller, tmp_path):
	github, package = newer_release()
	nvda.message_box_answer = YES
	make_controller(github).check_now()
	drain(nvda)
	assert nvda.message_boxes[0][0].startswith("Version 0.3.0 of the eSpeak NG with MBROLA add-on is available.")
	assert nvda.spoken == ["Downloading the MBROLA add-on update..."]
	assert nvda.installed_bundles == [("mbrolaEspeak-0.3.0.nvda-addon", package)]
	assert nvda.restart_prompts == 1


def test_downloaded_package_is_deleted_after_installing(nvda, make_controller, monkeypatch, tmp_path):
	update_ui = importlib.import_module("globalPlugins.mbrolaVoiceManager.update_ui")
	monkeypatch.setattr(update_ui.tempfile, "mkdtemp", lambda prefix: str(tmp_path / "download"))
	github, _ = newer_release()
	nvda.message_box_answer = YES
	make_controller(github).check_now()
	drain(nvda)
	assert len(nvda.installed_bundles) == 1
	assert not (tmp_path / "download").exists()


def test_no_restart_prompt_when_nvda_does_not_install(nvda, make_controller):
	github, _ = newer_release()
	nvda.message_box_answer = YES
	nvda.install_result = False  # the user cancelled NVDA's own confirmation, or it is incompatible
	make_controller(github).check_now()
	drain(nvda)
	assert len(nvda.installed_bundles) == 1 and nvda.restart_prompts == 0


def test_a_tampered_download_is_never_installed(nvda, make_controller):
	package = make_package(version="0.3.0")
	tampered = bytearray(package)
	tampered[len(tampered) // 2] ^= 0xFF
	github = FakeGitHub(release_json("v0.3.0", package=package), bytes(tampered))
	nvda.message_box_answer = YES
	make_controller(github).check_now()
	drain(nvda)
	assert nvda.installed_bundles == []
	assert nvda.message_boxes[-1][0] == (
		"The MBROLA add-on update was not installed. "
		"The downloaded file is damaged: its checksum does not match the published one."
	)


def test_second_check_while_busy_is_refused(nvda, make_controller):
	github, _ = newer_release()
	controller = make_controller(github)
	controller.check_now()  # result is queued, not shown yet
	controller.check_now()
	assert nvda.spoken == ["The MBROLA add-on is already checking for updates."]
	assert len(github.fetched) == 1
	drain(nvda)
	controller.check_now()  # free again
	assert len(github.fetched) == 2


# --- automatic checks ---------------------------------------------------------------------


def test_automatic_check_at_most_once_a_day(nvda, make_controller):
	github = FakeGitHub(release_json("v0.2.0"))
	clock = Clock()
	controller = make_controller(github, clock)
	controller.check_automatically()
	drain(nvda)
	controller.check_automatically()
	clock.now += DAY - 1
	controller.check_automatically()
	assert len(github.fetched) == 1
	clock.now += 1
	controller.check_automatically()
	assert len(github.fetched) == 2
	assert nvda.message_boxes == []  # "up to date" is only said when asked


def test_automatic_check_is_silent_when_offline(nvda, make_controller):
	# The controller's own copy of the module (tests also import ``updates`` as a top-level package).
	errors = importlib.import_module("globalPlugins.mbrolaVoiceManager.updates.errors")

	class Offline(FakeGitHub):
		def fetch_json(self, url):
			raise errors.UpdateError(errors.Problem.NETWORK, "no route to host")

	make_controller(Offline()).check_automatically()
	drain(nvda)
	assert nvda.message_boxes == []
	assert any("no route to host" in str(msg) for _, msg in nvda.log.records)


def test_declined_version_is_not_offered_again_automatically(nvda, make_controller):
	github, _ = newer_release()
	clock = Clock()
	controller = make_controller(github, clock)
	nvda.message_box_answer = NO
	controller.check_automatically()
	drain(nvda)
	assert len(nvda.message_boxes) == 1
	assert "will not be offered again when NVDA starts" in nvda.message_boxes[0][0]
	clock.now += 2 * DAY
	controller.check_automatically()
	drain(nvda)
	assert len(nvda.message_boxes) == 1  # quiet about 0.3.0 now
	controller.check_now()
	drain(nvda)
	assert len(nvda.message_boxes) == 2  # but asking by hand still offers it
	assert nvda.installed_bundles == []


def test_auto_check_can_be_turned_off(nvda, make_controller):
	github = FakeGitHub(release_json("v0.3.0"))
	controller = make_controller(github)
	assert controller.auto_check is True
	controller.auto_check = False
	assert make_controller(github).auto_check is False  # saved
	controller.check_automatically()
	assert github.fetched == []


# --- wiring in the global plugin and the settings panel ---------------------------------------


def test_plugin_gives_the_panel_an_update_controller_and_checks_after_startup(nvda, monkeypatch):
	plugin_mod = importlib.import_module("globalPlugins.mbrolaVoiceManager")
	panel_mod = importlib.import_module("globalPlugins.mbrolaVoiceManager.panel")
	made = []

	class FakeController:
		def check_automatically(self):
			made.append("checked")

	monkeypatch.setattr(plugin_mod, "_make_update_controller", lambda: made.append("made") or FakeController())
	monkeypatch.setattr(plugin_mod, "_offer_voices_if_first_run", lambda: None)
	plugin = plugin_mod.GlobalPlugin()
	assert isinstance(panel_mod.MbrolaVoicesPanel.updates, FakeController)
	assert made == ["made"]  # the check itself waits for NVDA's main loop
	drain(nvda)
	assert made == ["made", "checked"]
	plugin.terminate()
	assert panel_mod.MbrolaVoicesPanel.updates is None


@pytest.mark.parametrize("flag", ["secure", "launcher"])
def test_no_updates_on_secure_screens_or_in_the_installer(nvda, monkeypatch, flag):
	plugin_mod = importlib.import_module("globalPlugins.mbrolaVoiceManager")
	panel_mod = importlib.import_module("globalPlugins.mbrolaVoiceManager.panel")
	setattr(importlib.import_module("globalVars").appArgs, flag, True)
	monkeypatch.setattr(plugin_mod, "_make_update_controller", lambda: pytest.fail("must not be created"))
	plugin_mod.GlobalPlugin()
	assert panel_mod.MbrolaVoicesPanel.updates is None
	assert nvda.call_after == []


def test_real_controller_uses_the_addon_manifest_and_config_folder(nvda):
	plugin_mod = importlib.import_module("globalPlugins.mbrolaVoiceManager")
	nvda.addon_version = "0.2.0"
	controller = plugin_mod._make_update_controller()
	assert controller._name == "mbrolaEspeak" and controller._version == "0.2.0"
	assert str(controller._settings_file).endswith("mbrolaEspeakUpdates.json")
	assert controller._settings_file.parent.as_posix() == nvda.globalVars.appArgs.configPath.replace("\\", "/")
