"""Registers the "MBROLA voices" settings panel and shows the first-run message."""

import addonHandler
import globalPluginHandler
import globalVars
import gui
import wx
from gui.settingsDialogs import NVDASettingsDialog
from logHandler import log

from . import welcome
from .links import open_voices_page
from .panel import MbrolaVoicesPanel

addonHandler.initTranslation()


def _offer_voices_if_first_run() -> None:
	from synthDrivers.mbrola_espeak import get_layout
	from synthDrivers.mbrola_espeak.core.voice_library import VoiceLibrary

	layout = get_layout()
	installed = len(VoiceLibrary(layout).installed_voices())
	if not welcome.should_offer_voices(installed, layout.voice_store_dir):
		return
	welcome.remember_offered(layout.voice_store_dir)
	answer = gui.messageBox(
		# Translators: first-run message of the MBROLA add-on.
		_(
			"No MBROLA voices are installed yet, so the eSpeak NG with MBROLA synthesizer cannot speak. "
			"Do you want to open the voice download page in your web browser now?\n\n"
			"After downloading, import the voices in NVDA Settings, MBROLA voices category.",
		),
		# Translators: title of the first-run message of the MBROLA add-on.
		_("MBROLA voices"),
		wx.YES_NO | wx.ICON_QUESTION,
	)
	if answer == wx.YES:
		open_voices_page()


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def __init__(self):
		super().__init__()
		NVDASettingsDialog.categoryClasses.append(MbrolaVoicesPanel)
		# Never open a browser from the Windows sign-in or other secure screens.
		if not getattr(globalVars.appArgs, "secure", False):
			# Wait until NVDA's main loop is running before showing a dialog.
			wx.CallAfter(self._first_run)

	@staticmethod
	def _first_run():
		try:
			_offer_voices_if_first_run()
		except Exception:
			log.error("MBROLA add-on: first-run message failed", exc_info=True)

	def terminate(self):
		try:
			NVDASettingsDialog.categoryClasses.remove(MbrolaVoicesPanel)
		except ValueError:
			pass
		super().terminate()
