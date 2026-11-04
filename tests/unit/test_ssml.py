import pytest
from core.speech_items import Break, CharacterMode, Index, LangChange, Prosody, Text
from core.ssml import build_ssml, escape_text, normalize_lang


def test_plain_text_is_escaped():
	assert build_ssml([Text("a < b & c > d\x01")]) == "a &lt; b &amp; c &gt; d"


def test_marks_and_breaks():
	ssml = build_ssml([Text("one"), Index(1), Text("two"), Break(250), Index(2)])
	assert ssml == 'one<mark name="1"/>two<break time="250ms"/><mark name="2"/>'


def test_break_is_clamped():
	assert build_ssml([Break(-5)]) == '<break time="0ms"/>'
	assert build_ssml([Break(999_999)]) == '<break time="10000ms"/>'


def test_character_mode_open_and_close():
	ssml = build_ssml([CharacterMode(True), Text("abc"), CharacterMode(False), Text(" word")])
	assert ssml == '<say-as interpret-as="characters">abc</say-as> word'


def test_unclosed_tags_are_closed_at_the_end():
	ssml = build_ssml([Prosody("pitch", 1.5), CharacterMode(True), Text("x")])
	assert ssml == '<prosody pitch="150%"><say-as interpret-as="characters">x</say-as></prosody>'


def test_prosody_combines_and_resets():
	ssml = build_ssml(
		[
			Prosody("pitch", 1.2),
			Text("a"),
			Prosody("rate", 0.5),
			Text("b"),
			Prosody("pitch", 1.0),
			Text("c"),
			Prosody("rate", 1.0),
			Text("d"),
		],
	)
	assert ssml == (
		'<prosody pitch="120%">a</prosody>'
		'<prosody rate="50%" pitch="120%">b</prosody>'
		'<prosody rate="50%">c</prosody>'
		"d"
	)


def test_tags_stay_nested_when_outer_changes():
	ssml = build_ssml([CharacterMode(True), Text("a"), Prosody("volume", 0.8), Text("b")])
	assert ssml == (
		'<say-as interpret-as="characters">a</say-as>'
		'<prosody volume="80%"><say-as interpret-as="characters">b</say-as></prosody>'
	)


def test_lang_change():
	ssml = build_ssml([Text("hi"), LangChange("fr_FR"), Text("salut"), LangChange(None), Text("bye")])
	assert ssml == 'hi<voice xml:lang="fr-FR">salut</voice>bye'


def test_invalid_lang_is_ignored():
	assert build_ssml([LangChange('x" onload="'), Text("t")]) == "t"


def test_redundant_changes_produce_no_tags():
	assert build_ssml([CharacterMode(False), LangChange(None), Text("t")]) == "t"


def test_unknown_item_type():
	with pytest.raises(TypeError):
		build_ssml([object()])


def test_helpers():
	assert escape_text("<>") == "&lt;&gt;"
	assert normalize_lang("pt_BR") == "pt-BR"
	assert normalize_lang("") is None
