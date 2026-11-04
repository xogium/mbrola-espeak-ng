from pathlib import Path

import pytest
from core.audio import Chunk, split_at_marks
from core.layout import VOICE_STORE_DIR_NAME, AddonLayout
from core.params import INFLECTION, PITCH, RATE, VOLUME

# --- params -----------------------------------------------------------------


@pytest.mark.parametrize("spec", [RATE, PITCH, INFLECTION, VOLUME])
def test_percent_round_trip(spec):
	for percent in range(0, 101):
		assert spec.to_percent(spec.from_percent(percent)) == percent


def test_rate_range_matches_espeak():
	assert RATE.from_percent(0) == 80
	assert RATE.from_percent(100) == 450


def test_values_are_clamped():
	assert PITCH.from_percent(-10) == 0
	assert PITCH.from_percent(500) == 100
	assert RATE.to_percent(10_000) == 100


# --- audio -------------------------------------------------------------------


def test_no_marks_gives_one_chunk():
	assert split_at_marks(100, 0, []) == [Chunk(0, 100, None)]


def test_marks_split_at_sample_offsets():
	chunks = split_at_marks(1000, 0, [(1, 100), (2, 300)])
	assert chunks == [Chunk(0, 200, 1), Chunk(200, 600, 2), Chunk(600, 1000, None)]


def test_offsets_are_relative_to_samples_before_chunk():
	chunks = split_at_marks(1000, 1000, [(7, 1250)])
	assert chunks == [Chunk(0, 500, 7), Chunk(500, 1000, None)]


def test_out_of_range_marks_are_clamped():
	chunks = split_at_marks(100, 1000, [(1, 10), (2, 99_999)])
	assert chunks == [Chunk(0, 0, 1), Chunk(0, 100, 2), Chunk(100, 100, None)]


def test_marks_without_audio():
	assert split_at_marks(0, 500, [(3, 500)]) == [Chunk(0, 0, 3), Chunk(0, 0, None)]


def test_chunks_never_go_backwards():
	chunks = split_at_marks(1000, 0, [(1, 300), (2, 100)])
	assert [c.end for c in chunks] == [600, 600, 1000]


# --- layout -------------------------------------------------------------------


def test_layout_paths():
	layout = AddonLayout.for_nvda(Path("/addon/synthDrivers/mbrola_espeak"), Path("/cfg"))
	assert layout.voice_store_dir == Path("/cfg") / VOICE_STORE_DIR_NAME
	assert layout.espeak_home == Path("/addon/synthDrivers/mbrola_espeak")
	assert layout.espeak_mbrola_dir == layout.espeak_data_dir / "mbrola"
	assert layout.mbrola_voice_definitions_dir == layout.espeak_data_dir / "voices" / "mb"
	assert layout.espeak_library.parent == layout.bin_dir


def test_layout_missing(tmp_path):
	layout = AddonLayout(driver_dir=tmp_path, voice_store_dir=tmp_path / "s", espeak_library_name="e", mbrola_library_name="m")
	assert len(layout.missing()) == 4
	(tmp_path / "bin").mkdir()
	(tmp_path / "bin" / "e").write_bytes(b"")
	(tmp_path / "bin" / "m").write_bytes(b"")
	(tmp_path / "espeak-ng-data" / "voices" / "mb").mkdir(parents=True)
	assert layout.missing() == []
