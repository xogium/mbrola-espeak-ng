"""Mapping between NVDA's 0-100 sliders and eSpeak NG parameter values."""

from __future__ import annotations

import dataclasses
import enum


class EspeakParameter(enum.IntEnum):
	"""``espeak_PARAMETER`` from speak_lib.h."""

	RATE = 1
	VOLUME = 2
	PITCH = 3
	RANGE = 4


@dataclasses.dataclass(frozen=True)
class ParameterSpec:
	parameter: EspeakParameter
	minimum: int
	maximum: int

	def from_percent(self, percent: float) -> int:
		percent = min(100.0, max(0.0, float(percent)))
		return int(round(self.minimum + (self.maximum - self.minimum) * percent / 100.0))

	def to_percent(self, value: int) -> int:
		span = self.maximum - self.minimum
		value = min(self.maximum, max(self.minimum, value))
		return int(round((value - self.minimum) * 100.0 / span))


# Same ranges as NVDA's built-in eSpeak driver (synthDrivers/_espeak.py).
RATE = ParameterSpec(EspeakParameter.RATE, 80, 450)
PITCH = ParameterSpec(EspeakParameter.PITCH, 0, 100)
INFLECTION = ParameterSpec(EspeakParameter.RANGE, 0, 100)
VOLUME = ParameterSpec(EspeakParameter.VOLUME, 0, 100)

DEFAULT_PERCENTS = {
	EspeakParameter.RATE: 30,
	EspeakParameter.PITCH: 40,
	EspeakParameter.RANGE: 75,
	EspeakParameter.VOLUME: 100,
}
