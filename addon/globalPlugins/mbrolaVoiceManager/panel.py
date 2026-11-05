"""The "MBROLA voices" category in NVDA's Settings dialog (wx only, no logic)."""

from __future__ import annotations

from pathlib import Path

import addonHandler
import gui
import synthDriverHandler
import wx
from gui import guiHelper, settingsDialogs
from gui.settingsDialogs import SettingsPanel
from logHandler import log

from .links import VOICES_DOWNLOAD_URL, open_voices_page
from .presenter import VoiceManagerPresenter

addonHandler.initTranslation()

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


# NVDA's own width for panel descriptions; fall back if a future NVDA renames it.
_DESCRIPTION_WIDTH = getattr(settingsDialogs, "PANEL_DESCRIPTION_WIDTH", 544)


class MbrolaVoicesPanel(SettingsPanel):
	# Translators: title of the settings category for managing MBROLA voices.
	title = _("MBROLA voices")
	# Shown at the top of the panel and also exposed as the panel's accessible
	# description, the same way NVDA's built-in panels do it. A bare static text
	# with no description gave a speech/braille mismatch ("unknown" in braille).
	# Translators: instructions at the top of the MBROLA voices settings category.
	panelDescription = _(
		"MBROLA voices are not included with this add-on because each has its own licence. "
		"Use the button below to open the download page ({url}). Then import a voice file (for example en1), a zip file, "
		"or a whole folder: every voice found in the folder and its subfolders is imported. "
		"Keep the original file names.",
	).format(url=VOICES_DOWNLOAD_URL)

	def makeSettings(self, settingsSizer):
		self._presenter = _make_presenter()
		helper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)
		description = helper.addItem(wx.StaticText(self, label=self.panelDescription))
		description.Wrap(self.scaleSize(_DESCRIPTION_WIDTH))
		# Translators: label of the list of installed MBROLA voices.
		self._list = helper.addLabeledControl(_("Installed &voices:"), wx.ListBox, choices=[])
		buttons = guiHelper.ButtonHelper(wx.HORIZONTAL)
		# Translators: button that opens the MBROLA voice download page in the web browser.
		self._website_button = buttons.addButton(self, label=_("&Get voices online..."))
		# Translators: button that opens a file dialog to import MBROLA voice files or zips.
		self._import_button = buttons.addButton(self, label=_("&Import files..."))
		# Translators: button that imports every MBROLA voice found in a folder.
		self._import_folder_button = buttons.addButton(self, label=_("Import &folder..."))
		# Translators: button that removes the selected MBROLA voice.
		self._remove_button = buttons.addButton(self, label=_("&Remove voice"))
		helper.addItem(buttons)
		self._website_button.Bind(wx.EVT_BUTTON, self._on_open_website)
		self._import_button.Bind(wx.EVT_BUTTON, self._on_import)
		self._import_folder_button.Bind(wx.EVT_BUTTON, self._on_import_folder)
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
			message=_("Choose MBROLA voice files or zip archives (several can be selected)"),
			# Translators: file type shown in the file dialog for importing MBROLA voices.
			wildcard=_("MBROLA voices and zip archives") + " (*.*)|*.*",
			style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE,
		) as dialog:
			if dialog.ShowModal() != wx.ID_OK:
				return
			paths = [Path(p) for p in dialog.GetPaths()]
		self._show(self._presenter.import_files(paths))

	def _on_open_website(self, evt) -> None:
		if not open_voices_page():
			gui.messageBox(
				# Translators: shown when the web browser could not be opened.
				_("Could not open the web browser. The address is {url}").format(url=VOICES_DOWNLOAD_URL),
# Translators: title of an error message in the MBROLA voices settings.
				_("MBROLA voices"),
				wx.OK | wx.ICON_ERROR,
				self,
			)

	def _on_import_folder(self, evt) -> None:
		with wx.DirDialog(
			self,
			# Translators: title of the folder dialog for importing every MBROLA voice in a folder.
			message=_("Choose a folder containing MBROLA voices"),
			style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST,
		) as dialog:
			if dialog.ShowModal() != wx.ID_OK:
				return
			folder = Path(dialog.GetPath())
		with wx.BusyCursor():
			outcome = self._presenter.import_files([folder])
		self._show(outcome)

	def _on_remove(self, evt) -> None:
		index = self._list.GetSelection()
		if index == wx.NOT_FOUND:
			return
		name = self._entries[index].name
		answer = gui.messageBox(
			# Translators: asks before removing an MBROLA voice; {name} is the voice, e.g. en1.
			_("Remove the MBROLA voice {name}?").format(name=name),
			# Translators: title of the message asking before removing an MBROLA voice.
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
# Translators: title of the result of importing or removing MBROLA voices.
			_("MBROLA voices"),
			wx.OK | (wx.ICON_ERROR if outcome.is_error else wx.ICON_INFORMATION),
			self,
		)

	def onSave(self):
		# Imports and removals take effect immediately; there is nothing to save.
		pass
