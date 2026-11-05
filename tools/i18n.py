#!/usr/bin/env python3
"""Translations of the add-on: extract messages, update ``.po`` files, check them, compile ``.mo``.

NVDA loads an add-on's translations from ``locale/<lang>/LC_MESSAGES/nvda.mo``
inside the add-on. Only the ``.po`` source is kept in the repository;
``tools/build_addon.py`` compiles it into the package. Everything here is
plain Python, so no gettext tools are needed, on Windows or in CI.

Messages are found by reading the add-on's Python files (never importing them):

* ``_("...")`` calls, used by the NVDA layer and the wx-free presenters, which
  receive NVDA's ``_`` as their ``translate`` argument;
* ``N_("...")`` calls, used by ``core`` for error messages it cannot translate
  itself (see ``core/errors.py``).

A ``# Translators:`` comment right above the call (or between ``_(`` and the
string) is passed on to translators.

Usage:
  python tools/i18n.py pot [--output FILE]   write a template for a new translation
  python tools/i18n.py update LANG           create or refresh locale/LANG/LC_MESSAGES/nvda.po
  python tools/i18n.py check                 report untranslated, fuzzy, obsolete and broken entries
"""

from __future__ import annotations

import argparse
import ast
import dataclasses
import re
import string
import struct
import sys
from collections.abc import Iterable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ADDON_DIR = REPO_ROOT / "addon"
DOMAIN = "nvda"
MARKERS = ("_", "N_")
_TRANSLATORS = "Translators:"


@dataclasses.dataclass
class Message:
	msgid: str
	comments: list[str] = dataclasses.field(default_factory=list)
	locations: list[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class PoEntry:
	msgid: str
	msgstr: str
	fuzzy: bool = False


class I18nError(Exception):
	"""A source file or a ``.po`` file cannot be used as it is."""


# --- extraction -------------------------------------------------------------------


def _translator_comment(lines: list[str], call_line: int, string_line: int) -> str | None:
	"""The ``# Translators:`` comment above line ``call_line`` or inside the call (1-based lines)."""
	inside = [lines[i].strip() for i in range(call_line, string_line - 1)]
	above = []
	i = call_line - 2
	while i >= 0 and lines[i].strip().startswith("#"):
		above.insert(0, lines[i].strip())
		i -= 1
	for block in (inside, above):
		comment = [c.lstrip("#").strip() for c in block if c.startswith("#")]
		for start, text in enumerate(comment):
			if text.startswith(_TRANSLATORS):
				return " ".join(comment[start:])
	return None


def extract_from_source(source: str, location: str) -> tuple[list[Message], list[str]]:
	"""Messages in one Python source, and problems such as ``_(f"...")`` that cannot be translated."""
	tree = ast.parse(source)
	lines = source.splitlines()
	messages: list[Message] = []
	problems: list[str] = []
	for node in ast.walk(tree):
		if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in MARKERS):
			continue
		where = f"{location}:{node.lineno}"
		if len(node.args) != 1 or node.keywords or not isinstance(node.args[0], ast.Constant):
			problems.append(f"{where}: {node.func.id}() needs exactly one plain string literal")
			continue
		if not isinstance(node.args[0].value, str):
			problems.append(f"{where}: {node.func.id}() needs a string")
			continue
		comment = _translator_comment(lines, node.lineno, node.args[0].lineno)
		messages.append(Message(node.args[0].value, [comment] if comment else [], [where]))
	messages.sort(key=lambda m: int(m.locations[0].rsplit(":", 1)[1]))
	return messages, problems


def extract(addon_dir: Path = ADDON_DIR) -> tuple[list[Message], list[str]]:
	"""Every translatable message of the add-on, in source order, merged by text."""
	merged: dict[str, Message] = {}
	problems: list[str] = []
	for path in sorted(addon_dir.rglob("*.py")):
		if "__pycache__" in path.parts:
			continue
		location = path.relative_to(addon_dir).as_posix()
		found, issues = extract_from_source(path.read_text(encoding="utf-8"), location)
		problems += issues
		for message in found:
			existing = merged.setdefault(message.msgid, Message(message.msgid))
			existing.locations += message.locations
			existing.comments += [c for c in message.comments if c not in existing.comments]
	return list(merged.values()), problems


# --- .po reading and writing -----------------------------------------------------


def _unquote(token: str, where: str) -> str:
	try:
		value = ast.literal_eval(token)
	except (SyntaxError, ValueError) as e:
		raise I18nError(f"{where}: not a valid quoted string") from e
	if not isinstance(value, str) or not token.startswith('"'):
		raise I18nError(f"{where}: not a valid quoted string")
	return value


def parse_po(text: str, name: str = "<po>") -> dict[str, PoEntry]:
	"""Entries of a ``.po`` file by msgid (the header has msgid ``""``). Plural forms are not supported."""
	entries: dict[str, PoEntry] = {}
	current: dict[str, str] = {}
	field: str | None = None
	fuzzy = False

	def finish(line_no: int) -> None:
		nonlocal current, field, fuzzy
		if current:
			if "msgid" not in current or "msgstr" not in current:
				raise I18nError(f"{name}:{line_no}: entry without msgid or msgstr")
			if current["msgid"] in entries:
				raise I18nError(f"{name}:{line_no}: duplicate msgid {current['msgid']!r}")
			entries[current["msgid"]] = PoEntry(current["msgid"], current["msgstr"], fuzzy)
		current, field, fuzzy = {}, None, False

	for line_no, raw in enumerate(text.splitlines(), 1):
		line = raw.strip()
		where = f"{name}:{line_no}"
		if not line:
			finish(line_no)
		elif line.startswith("#"):
			if field == "msgstr":
				finish(line_no)
			if line.startswith("#,") and "fuzzy" in (flag.strip() for flag in line[2:].split(",")):
				fuzzy = True
			elif line.startswith("#~"):
				continue  # obsolete entry kept by other tools
		elif line.startswith(("msgid_plural", "msgstr[", "msgctxt")):
			raise I18nError(f"{where}: plural forms and contexts are not supported")
		elif line.startswith(("msgid ", "msgstr ")):
			keyword, _, rest = line.partition(" ")
			if keyword == "msgid" and field == "msgstr":
				finish(line_no)
			field = keyword
			current[field] = _unquote(rest.strip(), where)
		elif line.startswith('"'):
			if field is None:
				raise I18nError(f"{where}: string outside an entry")
			current[field] += _unquote(line, where)
		else:
			raise I18nError(f"{where}: cannot read this line")
	finish(len(text.splitlines()) + 1)
	return entries


def _quote(value: str) -> str:
	escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\t", "\\t")
	parts = escaped.split("\n")
	pieces = [p + "\\n" for p in parts[:-1]] + ([parts[-1]] if parts[-1] else [])
	if len(pieces) <= 1:
		return f'"{pieces[0] if pieces else ""}"'
	return '""\n' + "\n".join(f'"{p}"' for p in pieces)


def default_header(language: str) -> str:
	return (
		"Project-Id-Version: mbrolaEspeak\n"
		f"Language: {language}\n"
		"MIME-Version: 1.0\n"
		"Content-Type: text/plain; charset=UTF-8\n"
		"Content-Transfer-Encoding: 8bit\n"
	)


def render_po(messages: Iterable[Message], translations: dict[str, PoEntry], header: str) -> str:
	"""A ``.po`` file for ``messages``. Existing translations are kept; obsolete ones are dropped."""
	out = [f"msgid {_quote('')}", f"msgstr {_quote(header)}", ""]
	for m in messages:
		out += [f"#. {c}" for c in m.comments]
		out += [f"#: {loc}" for loc in m.locations]
		entry = translations.get(m.msgid)
		if entry is not None and entry.fuzzy:
			out.append("#, fuzzy")
		out += [f"msgid {_quote(m.msgid)}", f"msgstr {_quote(entry.msgstr if entry else '')}", ""]
	return "\n".join(out)


# --- checks -----------------------------------------------------------------------


def placeholders(text: str) -> set[str]:
	"""Names used in ``str.format`` fields: ``"{name}, {rate} Hz"`` -> ``{"name", "rate"}``."""
	try:
		return {field for _, field, _, _ in string.Formatter().parse(text) if field is not None}
	except ValueError:
		return {"<unbalanced braces>"}


def check_catalog(messages: Iterable[Message], entries: dict[str, PoEntry], name: str) -> tuple[list[str], list[str]]:
	"""``(errors, warnings)`` for one ``.po`` file.

	Errors break the add-on at run time (a translation whose ``{placeholders}``
	differ makes ``.format()`` fail). Warnings only mean English is shown.
	"""
	errors: list[str] = []
	warnings: list[str] = []
	wanted = {m.msgid for m in messages}
	for msgid in sorted(wanted):
		entry = entries.get(msgid)
		if entry is None:
			warnings.append(f"{name}: missing {msgid!r}")
		elif entry.fuzzy:
			warnings.append(f"{name}: fuzzy {msgid!r}")
		elif not entry.msgstr:
			warnings.append(f"{name}: untranslated {msgid!r}")
		elif placeholders(entry.msgstr) != placeholders(msgid):
			errors.append(f"{name}: placeholders differ for {msgid!r}: {entry.msgstr!r}")
	for msgid in sorted(set(entries) - wanted - {""}):
		warnings.append(f"{name}: obsolete {msgid!r}")
	return errors, warnings


def po_files(addon_dir: Path = ADDON_DIR) -> dict[str, Path]:
	"""``{language: path}`` for every ``locale/<lang>/LC_MESSAGES/nvda.po``."""
	return {p.parent.parent.name: p for p in sorted((addon_dir / "locale").glob(f"*/LC_MESSAGES/{DOMAIN}.po"))}


# --- .mo compilation -------------------------------------------------------------


def compile_mo(entries: dict[str, PoEntry]) -> bytes:
	"""GNU ``.mo`` bytes, as ``msgfmt`` writes them. Fuzzy and empty translations are left out."""
	catalog = {e.msgid: e.msgstr for e in entries.values() if e.msgstr and (not e.fuzzy or e.msgid == "")}
	ids = sorted(catalog)
	originals = [i.encode("utf-8") for i in ids]
	translated = [catalog[i].encode("utf-8") for i in ids]
	count = len(ids)
	header_size = 7 * 4
	originals_table = header_size
	translations_table = originals_table + count * 8
	data_start = translations_table + count * 8
	tables: list[int] = []
	data = b""
	for group in (originals, translated):
		for s in group:
			tables += [len(s), data_start + len(data)]
			data += s + b"\0"
	header = struct.pack("<7I", 0x950412DE, 0, count, originals_table, translations_table, 0, data_start)
	return header + struct.pack(f"<{len(tables)}I", *tables) + data


def compile_po_file(path: Path) -> bytes:
	"""Check one ``.po`` file and compile it. Refuses entries that would break at run time."""
	messages, problems = extract(path.parents[3])
	if problems:
		raise I18nError("\n".join(problems))
	entries = parse_po(path.read_text(encoding="utf-8"), str(path))
	errors, _warnings = check_catalog(messages, entries, str(path))
	if errors:
		raise I18nError("\n".join(errors))
	return compile_mo(entries)


# --- command line -------------------------------------------------------------------


def _pot(messages: list[Message]) -> str:
	return render_po(messages, {}, default_header("")) + "\n"


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
	parser.add_argument("--addon-dir", type=Path, default=ADDON_DIR)
	commands = parser.add_subparsers(dest="command", required=True)
	pot = commands.add_parser("pot", help="write a translation template")
	pot.add_argument("--output", type=Path)
	update = commands.add_parser("update", help="create or refresh one language's .po file")
	update.add_argument("language", help="NVDA language code, for example fr or pt_BR")
	commands.add_parser("check", help="check every .po file")
	args = parser.parse_args(argv)

	messages, problems = extract(args.addon_dir)
	for problem in problems:
		print(problem, file=sys.stderr)
	if problems:
		return 1
	if args.command == "pot":
		text = _pot(messages)
		if args.output:
			args.output.write_text(text, encoding="utf-8")
		else:
			sys.stdout.write(text)
		return 0
	if args.command == "update":
		if not re.fullmatch(r"[a-z]{2,3}(_[A-Z]{2})?", args.language):
			parser.error(f"not an NVDA language code: {args.language}")
		path = args.addon_dir / "locale" / args.language / "LC_MESSAGES" / f"{DOMAIN}.po"
		existing = parse_po(path.read_text(encoding="utf-8"), str(path)) if path.is_file() else {}
		header = existing[""].msgstr if "" in existing else default_header(args.language)
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_text(render_po(messages, existing, header) + "\n", encoding="utf-8", newline="\n")
		print(path)
		return 0
	failed = False
	for language, path in po_files(args.addon_dir).items():
		errors, warnings = check_catalog(messages, parse_po(path.read_text(encoding="utf-8"), str(path)), language)
		for line in errors + warnings:
			print(line)
		failed = failed or bool(errors or warnings)
	return 1 if failed else 0


if __name__ == "__main__":
	sys.exit(main())
