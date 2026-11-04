"""Where every file lives. Pure path logic, no I/O except :meth:`AddonLayout.missing`.

Two roots:

* the *driver directory* (inside the installed add-on), which holds the
  native libraries and ``espeak-ng-data``. It is replaced on every add-on update.
* the *voice store* (inside the NVDA user configuration directory), which holds
  the MBROLA voices the user imported. It survives add-on updates.
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

if sys.platform == "win32":
	ESPEAK_LIBRARY_NAME = "espeak-ng-mbrola.dll"
	MBROLA_LIBRARY_NAME = "mbrola.dll"
else:
	# Linux test harness only; see native/linux-test-harness.
	ESPEAK_LIBRARY_NAME = "libespeak-ng.so"
	MBROLA_LIBRARY_NAME = "libmbrola.so"

VOICE_STORE_DIR_NAME = "mbrolaVoices"


@dataclasses.dataclass(frozen=True)
class AddonLayout:
	driver_dir: Path
	"""Folder containing ``bin/`` and ``espeak-ng-data/``."""
	voice_store_dir: Path
	"""Folder where imported MBROLA voices are kept."""
	espeak_library_name: str = ESPEAK_LIBRARY_NAME
	mbrola_library_name: str = MBROLA_LIBRARY_NAME

	@classmethod
	def for_nvda(cls, driver_dir: Path | str, config_dir: Path | str) -> AddonLayout:
		return cls(driver_dir=Path(driver_dir), voice_store_dir=Path(config_dir) / VOICE_STORE_DIR_NAME)

	@property
	def bin_dir(self) -> Path:
		return self.driver_dir / "bin"

	@property
	def espeak_library(self) -> Path:
		return self.bin_dir / self.espeak_library_name

	@property
	def mbrola_library(self) -> Path:
		return self.bin_dir / self.mbrola_library_name

	@property
	def espeak_home(self) -> Path:
		"""The path passed to ``espeak_Initialize`` (the folder that *contains* ``espeak-ng-data``)."""
		return self.driver_dir

	@property
	def espeak_data_dir(self) -> Path:
		return self.driver_dir / "espeak-ng-data"

	@property
	def mbrola_voice_definitions_dir(self) -> Path:
		"""eSpeak NG's ``voices/mb`` folder: one text file per MBROLA voice variant."""
		return self.espeak_data_dir / "voices" / "mb"

	@property
	def espeak_mbrola_dir(self) -> Path:
		"""Where eSpeak NG looks for MBROLA databases on Windows: ``<data>/mbrola/<name>``."""
		return self.espeak_data_dir / "mbrola"

	def missing(self) -> list[Path]:
		"""Required files or folders that do not exist. Empty means the install looks complete."""
		required = [self.espeak_library, self.mbrola_library, self.espeak_data_dir, self.mbrola_voice_definitions_dir]
		return [p for p in required if not p.exists()]
