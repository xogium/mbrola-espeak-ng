"""Registers the "MBROLA voices" settings panel. Nothing else."""

import globalPluginHandler
from gui.settingsDialogs import NVDASettingsDialog

from .panel import MbrolaVoicesPanel


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def __init__(self):
		super().__init__()
		NVDASettingsDialog.categoryClasses.append(MbrolaVoicesPanel)

	def terminate(self):
		try:
			NVDASettingsDialog.categoryClasses.remove(MbrolaVoicesPanel)
		except ValueError:
			pass
		super().terminate()
