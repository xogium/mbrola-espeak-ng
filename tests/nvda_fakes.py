"""Minimal stand-ins for the NVDA modules the add-on's adapter layer imports.

They implement only what the add-on uses, with the same names and
signatures as NVDA 2026.3. ``install()`` puts them in ``sys.modules`` and
puts ``addon/`` on ``sys.path`` so that ``import synthDrivers.mbrola_espeak``
works as it does inside NVDA.
"""

from __future__ import annotations

import builtins
import sys
import types
from pathlib import Path

ADDON_DIR = Path(__file__).resolve().parent.parent / "addon"


class _Action:
	def __init__(self):
		self.calls = []

	def notify(self, **kwargs):
		self.calls.append(kwargs)


class _Log:
	def __init__(self):
		self.records = []

	def _record(self, level):
		def log(msg, *args, **kwargs):
			self.records.append((level, msg))

		return log

	def __getattr__(self, level):
		return self._record(level)


class _AutoPropertyBase:
	"""Imitates NVDA's AutoPropertyObject: ``x.rate`` calls ``_get_rate``, ``x.rate = 1`` calls ``_set_rate``."""

	def __getattr__(self, name):
		getter = getattr(type(self), f"_get_{name}", None)
		if getter is None:
			raise AttributeError(name)
		return getter(self)

	def __setattr__(self, name, value):
		setter = getattr(type(self), f"_set_{name}", None)
		if setter is not None:
			setter(self, value)
		else:
			object.__setattr__(self, name, value)


class FakeSynthDriver(_AutoPropertyBase):
	@classmethod
	def VoiceSetting(cls):
		return ("setting", "voice")

	@classmethod
	def RateSetting(cls, minStep=1):
		return ("setting", "rate")

	@classmethod
	def PitchSetting(cls, minStep=1):
		return ("setting", "pitch")

	@classmethod
	def InflectionSetting(cls, minStep=1):
		return ("setting", "inflection")

	@classmethod
	def VolumeSetting(cls, minStep=1):
		return ("setting", "volume")

	def __init__(self):
		pass

	def _get_availableVoices(self):
		if "_availableVoices" not in self.__dict__:
			object.__setattr__(self, "_availableVoices", self._getAvailableVoices())
		return self.__dict__["_availableVoices"]


class VoiceInfo:
	def __init__(self, id, displayName, language=None):
		self.id = id
		self.displayName = displayName
		self.language = language


def _commands_module():
	m = types.ModuleType("speech.commands")

	class IndexCommand:
		def __init__(self, index):
			self.index = index

	class CharacterModeCommand:
		def __init__(self, state):
			self.state = state

	class LangChangeCommand:
		def __init__(self, lang):
			self.lang = lang

	class BreakCommand:
		def __init__(self, time=0):
			self.time = time

	class BaseProsodyCommand:
		def __init__(self, offset=0, multiplier=1):
			self.multiplier = multiplier

	class PitchCommand(BaseProsodyCommand):
		pass

	class RateCommand(BaseProsodyCommand):
		pass

	class VolumeCommand(BaseProsodyCommand):
		pass

	class PhonemeCommand:
		def __init__(self, ipa, text=None):
			self.ipa = ipa
			self.text = text

	for cls in (
		IndexCommand,
		CharacterModeCommand,
		LangChangeCommand,
		BreakCommand,
		BaseProsodyCommand,
		PitchCommand,
		RateCommand,
		VolumeCommand,
		PhonemeCommand,
	):
		setattr(m, cls.__name__, cls)
	return m


class State:
	"""Handles to the fakes so tests can inspect and configure them."""

	def __init__(self):
		self.log = _Log()
		self.synthIndexReached = _Action()
		self.synthDoneSpeaking = _Action()
		self.config_path = "/nonexistent"
		self.ui_language = "en_US"


def install(state: State | None = None) -> State:
	state = state or State()
	builtins.__dict__.setdefault("_", lambda s: s)

	modules = {}
	modules["addonHandler"] = types.SimpleNamespace(initTranslation=lambda: None)
	modules["globalVars"] = types.SimpleNamespace(appArgs=types.SimpleNamespace(configPath=state.config_path))
	modules["languageHandler"] = types.SimpleNamespace(
		getLanguage=lambda: state.ui_language,
		getLanguageDescription=lambda lang: {"en_uk": "English (UK)", "en_us": "English (US)"}.get(lang.lower()),
	)
	modules["logHandler"] = types.SimpleNamespace(log=state.log)
	modules["synthDriverHandler"] = types.SimpleNamespace(
		SynthDriver=FakeSynthDriver,
		VoiceInfo=VoiceInfo,
		synthIndexReached=state.synthIndexReached,
		synthDoneSpeaking=state.synthDoneSpeaking,
	)
	modules["speech"] = types.ModuleType("speech")
	modules["speech.commands"] = _commands_module()
	modules["speech"].commands = modules["speech.commands"]
	modules["config"] = types.SimpleNamespace(conf={"audio": {"outputDevice": "default"}})
	modules["nvwave"] = types.SimpleNamespace(WavePlayer=None)
	# GUI modules: only what is touched at import time. The wx panel itself is
	# not exercised here; its logic lives in the presenter, which is tested.

	class _GlobalPlugin:
		def __init__(self):
			pass

		def terminate(self):
			pass

	class _SettingsPanel:
		pass

	class _NVDASettingsDialog:
		categoryClasses = []

	modules["globalPluginHandler"] = types.SimpleNamespace(GlobalPlugin=_GlobalPlugin)
	modules["gui"] = types.ModuleType("gui")
	modules["gui.settingsDialogs"] = types.SimpleNamespace(
		SettingsPanel=_SettingsPanel,
		NVDASettingsDialog=_NVDASettingsDialog,
	)
	modules["gui.guiHelper"] = types.SimpleNamespace()
	modules["gui"].settingsDialogs = modules["gui.settingsDialogs"]
	modules["gui"].guiHelper = modules["gui.guiHelper"]
	modules["wx"] = types.ModuleType("wx")
	state.NVDASettingsDialog = _NVDASettingsDialog
	for name, module in modules.items():
		sys.modules[name] = module
	if str(ADDON_DIR) not in sys.path:
		sys.path.insert(0, str(ADDON_DIR))
	# Make sure the driver re-imports against these fakes.
	for name in list(sys.modules):
		if (
			name.startswith("synthDrivers.mbrola_espeak") and not name.startswith("synthDrivers.mbrola_espeak.core")
		) or name.startswith("globalPlugins.mbrolaVoiceManager"):
			del sys.modules[name]
	state.globalVars = modules["globalVars"]
	return state
