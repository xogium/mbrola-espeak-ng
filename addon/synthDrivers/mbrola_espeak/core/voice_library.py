"""Small facade joining catalog, store and sync, for the synth driver and the settings panel.

It adds no logic of its own beyond wiring. Each part can still be used and
tested on its own.
"""

from __future__ import annotations

from pathlib import Path

from .layout import AddonLayout
from .voice_catalog import MbrolaVoiceDefinition, VoiceCatalog
from .voice_store import InstalledVoice, VoiceStore
from .voice_sync import Linker, SyncReport, link_or_copy, sync_voices


class VoiceLibrary:
	def __init__(self, layout: AddonLayout, linker: Linker = link_or_copy):
		self._layout = layout
		self._linker = linker
		self.catalog = VoiceCatalog.load(layout.mbrola_voice_definitions_dir)
		self.store = VoiceStore(layout.voice_store_dir, self.catalog.database_names)

	def installed_voices(self) -> list[InstalledVoice]:
		return self.store.installed()

	def speakable_definitions(self) -> list[MbrolaVoiceDefinition]:
		"""eSpeak NG voices whose MBROLA database is installed."""
		return self.catalog.for_databases(self.store.installed_names())

	def import_path(self, source: Path, name: str | None = None) -> tuple[list[InstalledVoice], SyncReport]:
		imported = self.store.import_path(source, name)
		return imported, self.sync()

	def remove(self, name: str) -> SyncReport:
		self.store.remove(name)
		return self.sync()

	def sync(self) -> SyncReport:
		return sync_voices(
			self.store.installed(),
			self._layout.espeak_mbrola_dir,
			self.catalog.database_names,
			self._linker,
		)
