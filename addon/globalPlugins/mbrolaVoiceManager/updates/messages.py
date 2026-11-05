"""What the user is told about updates, as plain translatable sentences (NVDA reads them out)."""

from __future__ import annotations

from collections.abc import Callable

from .errors import Problem, UpdateError
from .releases import Release


class UpdateMessages:
	def __init__(self, translate: Callable[[str], str] = lambda s: s):
		""":param translate: NVDA's gettext function for this add-on."""
		self._ = translate

	@property
	def title(self) -> str:
		# Translators: title of the messages about updating the MBROLA add-on.
		return self._("MBROLA add-on update")

	def offer(self, release: Release, current_version: str, automatic: bool) -> str:
		_ = self._
		# Translators: offers to update the add-on; {new} and {current} are version numbers such as 0.3.0.
		text = _(
			"Version {new} of the eSpeak NG with MBROLA add-on is available. You have version {current}. "
			"Do you want to download and install it now? NVDA will then ask you to confirm the installation.",
		).format(new=release.version, current=current_version)
		if automatic:
			text += "\n\n" + _(
				# Translators: added to the update offer made when NVDA starts.
				"If you choose No, this version will not be offered again when NVDA starts. "
				"You can still check for updates in NVDA Settings, MBROLA voices category.",
			)
		return text

	def up_to_date(self, current_version: str) -> str:
		# Translators: result of checking for updates by hand; {version} is the installed version.
		return self._("You have the latest version of the eSpeak NG with MBROLA add-on ({version}).").format(
			version=current_version,
		)

	def busy(self) -> str:
		# Translators: spoken when an update check or download is already running.
		return self._("The MBROLA add-on is already checking for updates.")

	def downloading(self) -> str:
		# Translators: spoken when the download of an add-on update starts.
		return self._("Downloading the MBROLA add-on update...")

	def check_failed(self, error: UpdateError) -> str:
		# Translators: {reason} is one of the update problem sentences, e.g. "GitHub could not be reached (timed out)."
		return self._("Could not check for MBROLA add-on updates. {reason}").format(reason=self.reason(error))

	def download_failed(self, error: UpdateError) -> str:
		# Translators: {reason} is one of the update problem sentences. Nothing was installed.
		return self._("The MBROLA add-on update was not installed. {reason}").format(reason=self.reason(error))

	def reason(self, error: UpdateError) -> str:
		_ = self._
		detail = error.detail
		if error.problem is Problem.NETWORK:
			# Translators: an update problem; {detail} is the technical reason, e.g. "timed out".
			return _("GitHub could not be reached ({detail}).").format(detail=detail)
		if error.problem is Problem.BAD_RESPONSE:
			# Translators: an update problem; {detail} is the technical reason.
			return _("GitHub's answer could not be understood ({detail}).").format(detail=detail)
		if error.problem is Problem.NO_PACKAGE:
			# Translators: an update problem: a new release was published without its add-on file.
			return _("The new release does not contain the add-on package yet. Try again later.")
		if error.problem is Problem.DOWNLOAD_INCOMPLETE:
			# Translators: an update problem; {detail} says how much arrived, e.g. "1000 of 2000 bytes".
			return _("The download was incomplete ({detail}).").format(detail=detail)
		if error.problem is Problem.CHECKSUM_MISMATCH:
			# Translators: an update problem: the file's SHA-256 checksum does not match the published one.
			return _("The downloaded file is damaged: its checksum does not match the published one.")
		# Translators: an update problem; {detail} is the technical reason.
		return _("The downloaded file is not the expected add-on package ({detail}).").format(detail=detail)
