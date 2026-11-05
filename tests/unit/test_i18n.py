"""Translations: message extraction, .po handling, .mo compilation, and the French translation itself."""

import configparser
import gettext
import io
import zipfile
from pathlib import Path

import build_addon
import i18n
import pytest
from core.errors import N_, InvalidVoiceFileError, MbrolaEspeakError
from core.voice_store import VoiceStore

ADDON_DIR = build_addon.ADDON_DIR


def french() -> gettext.GNUTranslations:
	po = i18n.po_files(ADDON_DIR)["fr"]
	return gettext.GNUTranslations(io.BytesIO(i18n.compile_po_file(po)))


# --- extraction -------------------------------------------------------------------

SOURCE = """
def f():
	# Translators: shown above.
	a = _("Hello {name}")
	b = gui.messageBox(
		_(
			# Translators: shown inside the call,
			# over two lines.
			"Two "
			"parts",
		),
	)
	raise Error(N_("Core message {file}"), file="x")

def g():
	_(f"not {translatable}")
	_(name)
	other("not a message")
	_("Hello {name}")
"""


def test_extract_finds_messages_comments_and_problems():
	messages, problems = i18n.extract_from_source(SOURCE, "m.py")
	assert [m.msgid for m in messages] == ["Hello {name}", "Two parts", "Core message {file}", "Hello {name}"]
	assert messages[0].comments == ["Translators: shown above."]
	assert messages[1].comments == ["Translators: shown inside the call, over two lines."]
	assert messages[2].comments == []
	assert messages[0].locations == ["m.py:4"]
	assert problems == [
		"m.py:16: _() needs exactly one plain string literal",
		"m.py:17: _() needs exactly one plain string literal",
	]


def test_extract_merges_repeated_messages(tmp_path):
	(tmp_path / "a.py").write_text('# Translators: one.\n_("Same")\n', encoding="utf-8")
	(tmp_path / "b.py").write_text('# Translators: two.\n_("Same")\n', encoding="utf-8")
	messages, problems = i18n.extract(tmp_path)
	assert problems == []
	assert len(messages) == 1
	assert messages[0].locations == ["a.py:2", "b.py:2"]
	assert messages[0].comments == ["Translators: one.", "Translators: two."]


# --- .po files ----------------------------------------------------------------------


def test_render_and_parse_round_trip():
	messages = [
		i18n.Message("Plain", ["Translators: c."], ["x.py:1"]),
		i18n.Message('Quote " back\\slash\ttab\nsecond line'),
		i18n.Message("Untranslated"),
		i18n.Message("Fuzzy"),
	]
	translations = {
		"Plain": i18n.PoEntry("Plain", "Simple"),
		messages[1].msgid: i18n.PoEntry(messages[1].msgid, 'Guillemet « " »\nligne deux'),
		"Fuzzy": i18n.PoEntry("Fuzzy", "Flou", fuzzy=True),
		"Gone": i18n.PoEntry("Gone", "Parti"),
	}
	text = i18n.render_po(messages, translations, i18n.default_header("fr"))
	assert '#. Translators: c.\n#: x.py:1\nmsgid "Plain"' in text
	assert "Gone" not in text  # obsolete entries are dropped
	parsed = i18n.parse_po(text)
	assert parsed["Plain"].msgstr == "Simple"
	assert parsed[messages[1].msgid].msgstr == 'Guillemet « " »\nligne deux'
	assert parsed["Untranslated"].msgstr == ""
	assert parsed["Fuzzy"].fuzzy and not parsed["Plain"].fuzzy
	assert "Language: fr" in parsed[""].msgstr


@pytest.mark.parametrize(
	"text",
	['msgid "a"\nmsgid_plural "b"\n', 'msgid "a"\nmsgstr "b"\n\nmsgid "a"\nmsgstr "c"\n', '"orphan"\n', "junk\n"],
)
def test_parse_refuses_what_it_cannot_handle(text):
	with pytest.raises(i18n.I18nError):
		i18n.parse_po(text)


def test_check_catalog_reports_problems():
	messages = [i18n.Message(m) for m in ("{name} ok", "{name} broken", "missing", "empty", "fuzzy")]
	entries = {
		"{name} ok": i18n.PoEntry("{name} ok", "{name} bien"),
		"{name} broken": i18n.PoEntry("{name} broken", "{nom} cassé"),
		"empty": i18n.PoEntry("empty", ""),
		"fuzzy": i18n.PoEntry("fuzzy", "flou", fuzzy=True),
		"old": i18n.PoEntry("old", "vieux"),
	}
	errors, warnings = i18n.check_catalog(messages, entries, "xx")
	assert errors == ["xx: placeholders differ for '{name} broken': '{nom} cassé'"]
	assert warnings == ["xx: untranslated 'empty'", "xx: fuzzy 'fuzzy'", "xx: missing 'missing'", "xx: obsolete 'old'"]


def test_placeholders():
	assert i18n.placeholders("{name}, {rate} Hz") == {"name", "rate"}
	assert i18n.placeholders("none") == set()
	assert i18n.placeholders("{broken") == {"<unbalanced braces>"}


# --- .mo compilation -------------------------------------------------------------


def test_compiled_mo_is_read_by_gettext():
	entries = {
		"": i18n.PoEntry("", i18n.default_header("fr")),
		"Hello": i18n.PoEntry("Hello", "Bonjour"),
		"Ünïcode": i18n.PoEntry("Ünïcode", "Ça marche"),
		"Fuzzy": i18n.PoEntry("Fuzzy", "Flou", fuzzy=True),
		"Empty": i18n.PoEntry("Empty", ""),
	}
	t = gettext.GNUTranslations(io.BytesIO(i18n.compile_mo(entries)))
	assert t.gettext("Hello") == "Bonjour"
	assert t.gettext("Ünïcode") == "Ça marche"
	assert t.gettext("Fuzzy") == "Fuzzy"  # fuzzy translations are never used
	assert t.gettext("Empty") == "Empty"
	assert t.info()["language"] == "fr"


def test_compile_refuses_broken_placeholders(tmp_path):
	addon = tmp_path / "addon"
	(addon / "mod").mkdir(parents=True)
	(addon / "mod" / "m.py").write_text('_("{name} ok")\n', encoding="utf-8")
	po = addon / "locale" / "xx" / "LC_MESSAGES" / "nvda.po"
	po.parent.mkdir(parents=True)
	po.write_text('msgid "{name} ok"\nmsgstr "{nom} ok"\n', encoding="utf-8")
	with pytest.raises(i18n.I18nError, match="placeholders differ"):
		i18n.compile_po_file(po)


def test_update_command_keeps_translations_and_adds_new_messages(tmp_path):
	addon = tmp_path / "addon"
	addon.mkdir()
	(addon / "m.py").write_text('# Translators: t.\n_("Old")\n', encoding="utf-8")
	assert i18n.main(["--addon-dir", str(addon), "update", "xx"]) == 0
	po = addon / "locale" / "xx" / "LC_MESSAGES" / "nvda.po"
	po.write_text(po.read_text(encoding="utf-8").replace('msgid "Old"\nmsgstr ""', 'msgid "Old"\nmsgstr "Vieux"'))
	(addon / "m.py").write_text('_("Old")\n_("New")\n', encoding="utf-8")
	assert i18n.main(["--addon-dir", str(addon), "update", "xx"]) == 0
	entries = i18n.parse_po(po.read_text(encoding="utf-8"))
	assert entries["Old"].msgstr == "Vieux"
	assert entries["New"].msgstr == ""
	assert i18n.main(["--addon-dir", str(addon), "check"]) == 1  # "New" is untranslated


# --- the add-on's own messages and the French translation ------------------------------


def test_every_message_in_the_addon_is_extractable_and_explained():
	messages, problems = i18n.extract(ADDON_DIR)
	assert problems == []
	assert len(messages) > 30
	unexplained = [m.msgid for m in messages if not m.comments]
	assert unexplained == [], "add a '# Translators:' comment above these"


def test_french_translation_is_complete_and_correct():
	messages, _ = i18n.extract(ADDON_DIR)
	po = i18n.po_files(ADDON_DIR)["fr"]
	errors, warnings = i18n.check_catalog(messages, i18n.parse_po(po.read_text(encoding="utf-8")), "fr")
	assert errors == []
	assert warnings == [], "run: python tools/i18n.py update fr, then translate"


@pytest.mark.parametrize("language", sorted(i18n.po_files(ADDON_DIR)))
def test_accelerator_keys_are_kept(language):
	entries = i18n.parse_po(i18n.po_files(ADDON_DIR)[language].read_text(encoding="utf-8"))
	for entry in entries.values():
		if entry.msgid and entry.msgstr:
			assert entry.msgstr.count("&") == entry.msgid.count("&"), entry.msgid


def test_french_settings_panel_accelerators_do_not_clash():
	t = french()
	labels = ["Installed &voices:", "&Get voices online...", "&Import files...", "Import &folder...", "&Remove voice"]
	keys = [t.gettext(label).split("&", 1)[1][0].lower() for label in labels]
	assert len(set(keys)) == len(keys), keys


@pytest.mark.parametrize("language", sorted(i18n.po_files(ADDON_DIR)))
def test_each_translation_has_a_manifest_and_a_user_guide(language):
	manifest = ADDON_DIR / "locale" / language / "manifest.ini"
	parser = configparser.ConfigParser(interpolation=None)
	parser.optionxform = str
	parser.read_string("[addon]\n" + manifest.read_text(encoding="utf-8"))
	# NVDA only takes these two keys from a translated manifest.
	assert set(parser["addon"]) == {"summary", "description"}
	assert all(v.strip('"') for v in parser["addon"].values())
	doc = ADDON_DIR / "doc" / language / build_addon.read_manifest(ADDON_DIR)["docFileName"]
	assert f'<html lang="{language}">' in doc.read_text(encoding="utf-8")


# --- translated core errors --------------------------------------------------------------


def test_core_error_keeps_english_text_and_can_be_translated():
	e = InvalidVoiceFileError(N_("Could not read {file}: {reason}"), file="en1", reason="denied")
	assert str(e) == "Could not read en1: denied"
	assert e.translated(french().gettext) == "Impossible de lire en1 : denied"


def test_core_error_without_values_may_contain_braces():
	e = MbrolaEspeakError("espeak_SetParameter failed {x}")
	assert str(e) == "espeak_SetParameter failed {x}"
	assert e.translated(lambda s: s) == "espeak_SetParameter failed {x}"


def test_broken_translation_falls_back_to_english():
	e = InvalidVoiceFileError(N_("Could not read {file}: {reason}"), file="en1", reason="denied")
	assert e.translated(lambda s: "Lecture de {fichier} impossible") == "Could not read en1: denied"


def test_real_import_error_in_french(tmp_path):
	junk = tmp_path / "en1"
	junk.write_bytes(b"<html>not a voice</html>")
	with pytest.raises(InvalidVoiceFileError) as caught:
		VoiceStore(tmp_path / "store", {"en1"}).import_path(junk)
	assert caught.value.translated(french().gettext) == (
		"Ce n'est pas un fichier de voix MBROLA (la signature MBROLA est absente)."
	)


# --- packaging -------------------------------------------------------------------------


def test_package_ships_compiled_french_and_no_po(tmp_path):
	target = build_addon.build(ADDON_DIR, tmp_path / "dist", allow_missing_native=True)
	with zipfile.ZipFile(target) as z:
		names = set(z.namelist())
		mo = z.read("locale/fr/LC_MESSAGES/nvda.mo")
	assert "locale/fr/manifest.ini" in names
	assert "doc/fr/readme.html" in names
	assert not any(n.endswith((".po", ".pot")) for n in names)
	assert gettext.GNUTranslations(io.BytesIO(mo)).gettext("MBROLA voices") == "Voix MBROLA"


def test_package_refuses_a_broken_translation(tmp_path):
	import shutil

	addon = tmp_path / "addon"
	shutil.copytree(ADDON_DIR, addon, ignore=shutil.ignore_patterns("__pycache__", "bin", "espeak-ng-data"))
	po = addon / "locale" / "fr" / "LC_MESSAGES" / "nvda.po"
	po.write_text(
		po.read_text(encoding="utf-8").replace("Importées : {names}.", "Importées : {noms}."), encoding="utf-8"
	)
	with pytest.raises(SystemExit, match="translation is broken"):
		build_addon.build(addon, tmp_path / "dist", allow_missing_native=True)


def test_should_not_ship_translation_sources():
	from pathlib import PurePosixPath

	assert not build_addon.should_include(PurePosixPath("locale/fr/LC_MESSAGES/nvda.po"))
	assert build_addon.should_include(PurePosixPath("locale/fr/manifest.ini"))
	assert isinstance(ADDON_DIR, Path)
