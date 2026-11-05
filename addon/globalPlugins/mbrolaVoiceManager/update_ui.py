"""NVDA side of add-on updates: background threads, dialogs, and NVDA's own add-on installer.

All decisions are in the ``updates`` package. This class only moves work off
NVDA's main thread, shows what ``updates.messages`` says, and hands a checked
package to ``gui.addonGui.installAddon``, the same installer NVDA uses when
an ``.nvda-addon`` file is opened. That installer asks for confirmation,
checks compatibility with this NVDA version and replaces the old version
when NVDA restarts.
"""

from __future__ import annotations

import shutil
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

import addonHandler
import gui
import ui
import wx
from gui import addonGui
from logHandler import log

from .updates import download, releases, schedule, web
from .updates.errors import UpdateError
from .updates.messages import UpdateMessages

addonHandler.initTranslation()


def _run_in_thread(work: Callable[[], None]) -> None:
	threading.Thread(target=work, name="mbrolaEspeakUpdate", daemon=True).start()


class UpdateController:
	def __init__(
		self,
		addon_name: str,
		current_version: str,
		settings_file: Path,
		fetch_json: releases.FetchJson | None = None,
		open_url: download.OpenUrl | None = None,
		run_in_background: Callable[[Callable[[], None]], None] = _run_in_thread,
		clock: Callable[[], float] = time.time,
	):
		self._name = addon_name
		self._version = current_version
		self._settings_file = settings_file
		self._fetch_json = fetch_json or web.make_json_fetcher(current_version)
		self._open_url = open_url or web.make_opener(current_version)
		self._run = run_in_background
		self._clock = clock
		self._messages = UpdateMessages(_)
		self._busy = False

	# --- settings (used by the settings panel) ----------------------------------------

	@property
	def auto_check(self) -> bool:
		return schedule.load(self._settings_file).auto_check

	@auto_check.setter
	def auto_check(self, enabled: bool) -> None:
		settings = schedule.load(self._settings_file)
		if settings.auto_check != enabled:
			settings.auto_check = enabled
			schedule.save(self._settings_file, settings)

	# --- checking ------------------------------------------------------------------------

	def check_automatically(self) -> None:
		"""Check in the background if the user allows it and a day has passed. Silent unless there is an update."""
		settings = schedule.load(self._settings_file)
		now = self._clock()
		if not settings.is_due(now):
			return
		settings.last_check = now
		schedule.save(self._settings_file, settings)
		self._check(automatic=True)

	def check_now(self) -> None:
		"""Check because the user asked; every outcome is reported."""
		self._check(automatic=False)

	def _check(self, automatic: bool) -> None:
		if self._busy:
			if not automatic:
				ui.message(self._messages.busy())
			return
		self._busy = True

		def work() -> None:
			try:
				release = releases.find_update(self._fetch_json, self._version, self._name)
			except UpdateError as e:
				wx.CallAfter(self._on_check_failed, e, automatic)
			except Exception:
				log.error("MBROLA add-on: update check failed", exc_info=True)
				wx.CallAfter(self._finish)
			else:
				wx.CallAfter(self._on_checked, release, automatic)

		self._run(work)

	def _finish(self) -> None:
		self._busy = False

	def _on_check_failed(self, error: UpdateError, automatic: bool) -> None:
		self._busy = False
		log.info(f"MBROLA add-on: update check failed: {error}")
		if not automatic:
			self._show(self._messages.check_failed(error), wx.ICON_ERROR)

	def _on_checked(self, release: releases.Release | None, automatic: bool) -> None:
		self._busy = False
		if release is None:
			if not automatic:
				self._show(self._messages.up_to_date(self._version), wx.ICON_INFORMATION)
			return
		settings = schedule.load(self._settings_file)
		if not settings.should_offer(release.version, automatic):
			return
		answer = gui.messageBox(
			self._messages.offer(release, self._version, automatic),
			self._messages.title,
			wx.YES_NO | wx.ICON_QUESTION,
		)
		if answer == wx.YES:
			self._download(release)
		else:
			settings.declined_version = release.version
			schedule.save(self._settings_file, settings)

	# --- downloading and installing ----------------------------------------------------

	def _download(self, release: releases.Release) -> None:
		self._busy = True
		ui.message(self._messages.downloading())

		def work() -> None:
			folder = Path(tempfile.mkdtemp(prefix="mbrolaEspeakUpdate-"))
			try:
				package = download.download_package(release, folder, self._open_url, self._name)
			except UpdateError as e:
				shutil.rmtree(folder, ignore_errors=True)
				wx.CallAfter(self._on_download_failed, e)
			except Exception:
				shutil.rmtree(folder, ignore_errors=True)
				log.error("MBROLA add-on: update download failed", exc_info=True)
				wx.CallAfter(self._finish)
			else:
				wx.CallAfter(self._install, package)

		self._run(work)

	def _on_download_failed(self, error: UpdateError) -> None:
		self._busy = False
		log.warning(f"MBROLA add-on: update download failed: {error}")
		self._show(self._messages.download_failed(error), wx.ICON_ERROR)

	def _install(self, package: Path) -> None:
		self._busy = False
		try:
			gui.mainFrame.prePopup()
			try:
				installed = addonGui.installAddon(gui.mainFrame, str(package))
			finally:
				gui.mainFrame.postPopup()
		finally:
			# NVDA has extracted the package by now (or refused it); the download is no longer needed.
			shutil.rmtree(package.parent, ignore_errors=True)
		if installed:
			wx.CallAfter(addonGui.promptUserForRestart)

	def _show(self, message: str, icon: int) -> None:
		gui.messageBox(message, self._messages.title, wx.OK | icon)
