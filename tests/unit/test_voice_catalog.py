from core.voice_catalog import VoiceCatalog, parse_definition
from voice_fixtures import write_definitions

EN1 = """name english-mb-en1
language en-uk  3
language en-gb  3
language en 2
gender male

voicing 150
pitch 82 117
mbrola en1 en1_phtrans
"""


def test_parses_real_definition():
	d = parse_definition("mb-en1", EN1)
	assert d is not None
	assert d.identifier == "mb-en1"
	assert d.name == "english-mb-en1"
	assert d.database == "en1"
	assert d.languages == ("en-uk", "en-gb", "en")
	assert d.primary_language == "en-uk"
	assert d.gender == "male"


def test_definition_without_mbrola_line_is_ignored():
	assert parse_definition("en", "name english\nlanguage en\n") is None


def test_comments_and_blank_lines():
	text = "// a comment\n\nname  x y  // trailing\nmbrola de6 de6_phtrans // db\n"
	d = parse_definition("mb-de6", text)
	assert d.name == "x y"
	assert d.database == "de6"
	assert d.languages == ()
	assert d.primary_language is None


def test_name_defaults_to_identifier():
	assert parse_definition("mb-x1", "mbrola x1 x1_phtrans").name == "mb-x1"


def test_catalog_load_and_queries(tmp_path):
	d = write_definitions(tmp_path / "mb", {"mb-br1": "br1", "mb-br1-xex": "br1", "mb-en1": "en1"})
	(d / "README").write_text("not a voice")
	(d / "subdir").mkdir()
	catalog = VoiceCatalog.load(d)
	assert [x.identifier for x in catalog.definitions] == ["mb-br1", "mb-br1-xex", "mb-en1"]
	assert catalog.database_names == {"br1", "en1"}
	assert catalog.knows_database("en1") and not catalog.knows_database("zz9")
	assert [x.identifier for x in catalog.for_databases({"br1"})] == ["mb-br1", "mb-br1-xex"]
	assert catalog.by_identifier("mb-en1").database == "en1"
	assert catalog.by_identifier("nope") is None


def test_missing_directory_gives_empty_catalog(tmp_path):
	assert VoiceCatalog.load(tmp_path / "missing").definitions == ()


def _defs(*specs):
	from core.voice_catalog import MbrolaVoiceDefinition

	return [MbrolaVoiceDefinition(i, i, i[3:], tuple(langs), None) for i, langs in specs]


def test_choose_default_prefers_exact_region_then_language():
	from core.voice_catalog import choose_default

	defs = _defs(("mb-de6", ["de"]), ("mb-en1", ["en-uk", "en"]), ("mb-us1", ["en-us", "en"]))
	assert choose_default(defs, "en_US").identifier == "mb-us1"
	assert choose_default(defs, "en_GB").identifier == "mb-en1"  # falls back to language "en"
	assert choose_default(defs, "de_AT").identifier == "mb-de6"
	assert choose_default(defs, "ja").identifier == "mb-de6"  # first voice
	assert choose_default(defs, None).identifier == "mb-de6"
	assert choose_default([], "en") is None
