"""The "MBROLA voices" category in NVDA's Settings dialog (wx only, no logic)."""

from __future__ import annotations

from pathlib import Path

import addonHandler
import gui
import synthDriverHandler
import wx
from gui import guiHelper
from gui.settingsDialogs import SettingsPanel
from logHandler import log

from .presenter import VoiceManagerPresenter

addonHandler.initTranslation()

VOICES_URL = "https://github.com/numediart/MBROLA-voices"


def _make_presenter() -> VoiceManagerPresenter:
	from synthDrivers.mbrola_espeak import get_layout
	from synthDrivers.mbrola_espeak.core.errors import MbrolaEspeakError
	from synthDrivers.mbrola_espeak.core.voice_library import VoiceLibrary

	return VoiceManagerPresenter(VoiceLibrary(get_layout()), expected_errors=(MbrolaEspeakError,), translate=_)


def _reload_synth_if_active() -> None:
	from synthDrivers.mbrola_espeak import DRIVER_NAME

	synth = synthDriverHandler.getSynth()
	if synth is not None and synth.name == DRIVER_NAME:
		# Re-create the driver so its voice list includes the change.
		synthDriverHandler.setSynth(DRIVER_NAME)


class MbrolaVoicesPanel(SettingsPanel):
	# Translators: title of the settings category for managing MBROLA voices.
	title = _("MBROLA voices")

	def makeSettings(self, settingsSizer):
		self._presenter = _make_presenter()
		helper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)
		helper.addItem(
			wx.StaticText(
				self,
				label=_(
					"MBROLA voices are not included with this add-on because each has its own licence. "
					"Download a voice from {url}, then import the voice file (for example en1) "
					"or a zip file that contains it. Keep the original file name.",
				).format(url=VOICES_URL),
			),
		)
		# Translators: label of the list of installed MBROLA voices.
		self._list = helper.addLabeledControl(_("Installed &voices:"), wx.ListBox, choices=[])
		buttons = guiHelper.ButtonHelper(wx.HORIZONTAL)
		# Translators: button that opens a file dialog to import MBROLA voices.
		self._import_button = buttons.addButton(self, label=_("&Import voice..."))
		# Translators: button that removes the selected MBROLA voice.
		self._remove_button = buttons.addButton(self, label=_("&Remove voice"))
		helper.addItem(buttons)
		self._import_button.Bind(wx.EVT_BUTTON, self._on_import)
		self._remove_button.Bind(wx.EVT_BUTTON, self._on_remove)
		self._list.Bind(wx.EVT_LISTBOX, lambda evt: self._update_buttons())
		self._refresh()

	def _refresh(self, select: str | None = None) -> None:
		self._entries = self._presenter.entries()
		self._list.Set([e.label for e in self._entries])
		names = [e.name for e in self._entries]
		if names:
			self._list.SetSelection(names.index(select) if select in names else 0)
		self._update_buttons()

	def _update_buttons(self) -> None:
		self._remove_button.Enable(self._list.GetSelection() != wx.NOT_FOUND)

	def _on_import(self, evt) -> None:
		with wx.FileDialog(
			self,
			# Translators: title of the file dialog for importing MBROLA voices.
			message=_("Choose MBROLA voice files or zip archives"),
			wildcard=_("MBROLA voices and zip archives") + " (*.*)|*.*",
			style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE,
		) as dialog:
			if dialog.ShowModal() != wx.ID_OK:
				return
			paths = [Path(p) for p in dialog.GetPaths()]
		self._show(self._presenter.import_files(paths))

	def _on_remove(self, evt) -> None:
		index = self._list.GetSelection()
		if index == wx.NOT_FOUND:
			return
		name = self._entries[index].name
		answer = gui.messageBox(
			_("Remove the MBROLA voice {name}?").format(name=name),
			_("Confirm removal"),
			wx.YES_NO | wx.ICON_QUESTION,
			self,
		)
		if answer != wx.YES:
			return
		self._show(self._presenter.remove(name))

	def _show(self, outcome) -> None:
		self._refresh()
		if outcome.voices_changed:
			try:
				_reload_synth_if_active()
			except Exception:
				log.error("Could not reload the MBROLA synthesizer", exc_info=True)
		gui.messageBox(
			outcome.message,
			_("MBROLA voices"),
			wx.OK | (wx.ICON_ERROR if outcome.is_error else wx.ICON_INFORMATION),
			self,
		)

	def onSave(self):
		# Imports and removals take effect immediately; there is nothing to save.
		pass
