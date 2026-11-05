"""The "check automatically" setting, and when the next automatic check is due.

Kept in a small JSON file in NVDA's configuration folder (next to
``mbrolaVoices``), so it survives add-on updates. Automatic checks happen
at most once a day, and a version the user declined is not offered again
automatically (checking by hand still shows it).
"""

from __future__ import annotations

import dataclasses
import json
import os
import tempfile
from pathlib import Path

SETTINGS_FILE_NAME = "mbrolaEspeakUpdates.json"
CHECK_INTERVAL_SECONDS = 24 * 60 * 60


@dataclasses.dataclass
class UpdateSettings:
	auto_check: bool = True
	last_check: float = 0.0
	"""When the last automatic check started, as ``time.time()``."""
	declined_version: str | None = None

	def is_due(self, now: float) -> bool:
		"""True if an automatic check should run now. A clock set backwards also makes it due."""
		if not self.auto_check:
			return False
		elapsed = now - self.last_check
		return elapsed >= CHECK_INTERVAL_SECONDS or elapsed < 0

	def should_offer(self, version: str, automatic: bool) -> bool:
		"""Automatic checks stay quiet about a version the user already declined."""
		return not (automatic and version == self.declined_version)


def settings_path(config_dir: Path | str) -> Path:
	return Path(config_dir) / SETTINGS_FILE_NAME


def _is_number(value: object) -> bool:
	return isinstance(value, int | float) and not isinstance(value, bool)


def load(path: Path) -> UpdateSettings:
	"""The saved settings, or the defaults if the file is missing or unreadable."""
	try:
		data = json.loads(Path(path).read_text(encoding="utf-8"))
	except (OSError, ValueError):
		return UpdateSettings()
	if not isinstance(data, dict):
		return UpdateSettings()
	defaults = UpdateSettings()
	auto_check = data.get("autoCheck")
	last_check = data.get("lastCheck")
	declined = data.get("declinedVersion")
	return UpdateSettings(
		auto_check=auto_check if isinstance(auto_check, bool) else defaults.auto_check,
		last_check=float(last_check) if _is_number(last_check) else defaults.last_check,
		declined_version=declined if isinstance(declined, str) else None,
	)


def save(path: Path, settings: UpdateSettings) -> None:
	"""Write the settings atomically, so a crash never leaves a half-written file."""
	path = Path(path)
	path.parent.mkdir(parents=True, exist_ok=True)
	data = {
		"autoCheck": settings.auto_check,
		"lastCheck": settings.last_check,
		"declinedVersion": settings.declined_version,
	}
	fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".partial", dir=path.parent)
	try:
		with os.fdopen(fd, "w", encoding="utf-8") as out:
			json.dump(data, out, indent="\t")
			out.write("\n")
		os.replace(tmp_name, path)
	except BaseException:
		Path(tmp_name).unlink(missing_ok=True)
		raise
