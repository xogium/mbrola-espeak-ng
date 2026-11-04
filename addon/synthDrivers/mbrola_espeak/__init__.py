"""NVDA synthesizer driver: eSpeak NG with MBROLA voices.

This module is an adapter. It turns NVDA's settings and speech sequences into
calls on the core (``core/``), and core callbacks into NVDA notifications.
Everything that can be decided without NVDA is decided in ``core``.
"""

from __future__ import annotations

import os
from collections import OrderedDict

import addonHandler
import globalVars
import languageHandler
from logHandler import log
from synthDriverHandler import SynthDriver as BaseSynthDriver
from synthDriverHandler import VoiceInfo, synthDoneSpeaking, synthIndexReached

from ._nvda_audio import WavePlayerSink
from ._nvda_commands import SUPPORTED_COMMANDS, to_speech_items
from .core.engine import SpeechEngine
from .core.errors import MbrolaEspeakError
from .core.espeak_binding import EspeakBinding
from .core.layout import AddonLayout
from .core.params import DEFAULT_PERCENTS, INFLECTION, PITCH, RATE, VOLUME, EspeakParameter, ParameterSpec
from .core.ssml import build_ssml
from .core.voice_catalog import MbrolaVoiceDefinition, choose_default
from .core.voice_library import VoiceLibrary

addonHandler.initTranslation()

DRIVER_NAME = "mbrola_espeak"
DRIVER_DIR = os.path.dirname(os.path.abspath(__file__))
# How long NVDA's thread waits for a voice change to be applied.
VOICE_CHANGE_TIMEOUT_SECONDS = 10


def get_layout() -> AddonLayout:
	return AddonLayout.for_nvda(DRIVER_DIR, globalVars.appArgs.configPath)


def voice_display_name(definition: MbrolaVoiceDefinition) -> str:
	language = definition.primary_language
	description = languageHandler.getLanguageDescription(language.replace("-", "_")) if language else None
	label = description or language or definition.name
	return f"{label}, MBROLA {definition.database} ({definition.identifier})"


class SynthDriver(BaseSynthDriver):
	name = DRIVER_NAME
	# Translators: name of the synthesizer in NVDA's synthesizer list.
	description = _("eSpeak NG with MBROLA")

	supportedSettings = (
		BaseSynthDriver.VoiceSetting(),
		BaseSynthDriver.RateSetting(),
		BaseSynthDriver.PitchSetting(),
		BaseSynthDriver.InflectionSetting(),
		BaseSynthDriver.VolumeSetting(),
	)
	supportedCommands = set(SUPPORTED_COMMANDS)
	supportedNotifications = {synthIndexReached, synthDoneSpeaking}

	_SPECS: dict[str, ParameterSpec] = {"rate": RATE, "pitch": PITCH, "inflection": INFLECTION, "volume": VOLUME}

	@classmethod
	def check(cls) -> bool:
		missing = get_layout().missing()
		if missing:
			log.debugWarning(f"{DRIVER_NAME}: add-on is incomplete, missing {missing}")
		return not missing

	def __init__(self):
		super().__init__()
		layout = get_layout()
		self._library = VoiceLibrary(layout)
		report = self._library.sync()
		if report.failed:
			log.warning(f"{DRIVER_NAME}: could not update some voices: {report.failed}")
		self._definitions = self._library.speakable_definitions()
		if not self._definitions:
			raise MbrolaEspeakError(
				"No MBROLA voices are installed. Import one in NVDA Settings, MBROLA voices category.",
			)
		binding = EspeakBinding(layout.espeak_library, layout.mbrola_library, layout.espeak_home)
		log.info(f"{DRIVER_NAME}: eSpeak NG {binding.version()}, {len(self._definitions)} MBROLA voices")
		self._engine = SpeechEngine(
			binding,
			WavePlayerSink(),
			on_index=self._on_index,
			on_done=self._on_done,
			on_error=self._on_error,
		)
		default = choose_default(self._definitions, languageHandler.getLanguage())
		self._set_voice(default.identifier)
		for setting, parameter in (
			("rate", EspeakParameter.RATE),
			("pitch", EspeakParameter.PITCH),
			("inflection", EspeakParameter.RANGE),
			("volume", EspeakParameter.VOLUME),
		):
			setattr(self, setting, DEFAULT_PERCENTS[parameter])

	def terminate(self):
		self._engine.terminate()

	# --- speech -----------------------------------------------------------------

	def speak(self, speechSequence):
		items = to_speech_items(speechSequence, on_unknown=lambda item: log.error(f"Unknown speech: {item!r}"))
		self._engine.speak(build_ssml(items))

	def cancel(self):
		self._engine.cancel()

	def pause(self, switch):
		self._engine.pause(switch)

	def _on_index(self, index: int):
		synthIndexReached.notify(synth=self, index=index)

	def _on_done(self):
		synthDoneSpeaking.notify(synth=self)

	def _on_error(self, error: BaseException):
		log.error(f"{DRIVER_NAME}: speech engine error", exc_info=error)

	# --- voices -----------------------------------------------------------------

	def _getAvailableVoices(self):
		return OrderedDict(
			(d.identifier, VoiceInfo(d.identifier, voice_display_name(d), d.primary_language))
			for d in self._definitions
		)

	def _get_voice(self):
		return self._engine.voice or ""

	def _set_voice(self, identifier):
		if identifier not in self.availableVoices:
			log.debugWarning(f"{DRIVER_NAME}: ignoring unknown voice {identifier!r}")
			return
		self._engine.set_voice(identifier).result(VOICE_CHANGE_TIMEOUT_SECONDS)

	# --- numeric settings (0-100 in NVDA) -----------------------------------------

	def _get_percent(self, setting: str) -> int:
		spec = self._SPECS[setting]
		value = self._engine.get_parameter(spec.parameter)
		return DEFAULT_PERCENTS[spec.parameter] if value is None else spec.to_percent(value)

	def _set_percent(self, setting: str, percent: int) -> None:
		spec = self._SPECS[setting]
		self._engine.set_parameter(spec.parameter, spec.from_percent(percent))

	def _get_rate(self):
		return self._get_percent("rate")

	def _set_rate(self, value):
		self._set_percent("rate", value)

	def _get_pitch(self):
		return self._get_percent("pitch")

	def _set_pitch(self, value):
		self._set_percent("pitch", value)

	def _get_inflection(self):
		return self._get_percent("inflection")

	def _set_inflection(self, value):
		self._set_percent("inflection", value)

	def _get_volume(self):
		return self._get_percent("volume")

	def _set_volume(self, value):
		self._set_percent("volume", value)
