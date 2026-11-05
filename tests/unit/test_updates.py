"""The NVDA-free update logic: versions, GitHub releases, downloading, schedule, messages, HTTP."""

import gettext
import hashlib
import http.server
import io
import json
import threading

import i18n
import pytest
from update_fixtures import API_URL, REPOSITORY, FakeGitHub, make_package, release_json
from updates import download, releases, schedule, web
from updates.errors import Problem, UpdateError
from updates.messages import UpdateMessages
from updates.version import is_newer, parse_version

# --- versions ----------------------------------------------------------------------


@pytest.mark.parametrize(
	"text,expected",
	[
		("0.2.0", (0, 2, 0)),
		("v0.3.0", (0, 3, 0)),
		("1.2", (1, 2, 0)),
		("2", (2, 0, 0)),
		(" v10.0.1 ", (10, 0, 1)),
		("0.3.0-beta1", None),
		("latest", None),
		("", None),
	],
)
def test_parse_version(text, expected):
	assert parse_version(text) == expected


@pytest.mark.parametrize(
	"candidate,current,newer",
	[
		("v0.3.0", "0.2.0", True),
		("0.10.0", "0.9.0", True),  # numeric, not alphabetical
		("v0.2.0", "0.2.0", False),
		("v0.1.9", "0.2.0", False),
		("v0.3.0-rc1", "0.2.0", False),  # pre-releases are never offered
		("v0.1.0", "0.3.0-dev", False),  # a development build is never "updated" backwards
	],
)
def test_is_newer(candidate, current, newer):
	assert is_newer(candidate, current) is newer


# --- releases ----------------------------------------------------------------------


def test_parse_release():
	package = make_package()
	release = releases.parse_release(release_json(package=package), "mbrolaEspeak")
	assert release.version == "0.3.0"
	assert release.page_url == f"https://github.com/{REPOSITORY}/releases/tag/v0.3.0"
	assert release.package_name == "mbrolaEspeak-0.3.0.nvda-addon"
	assert release.package_url == (
		f"https://github.com/{REPOSITORY}/releases/download/v0.3.0/mbrolaEspeak-0.3.0.nvda-addon"
	)
	assert release.package_size == len(package)
	assert release.package_sha256 == hashlib.sha256(package).hexdigest()


def test_parse_release_prefers_this_addons_package_and_ignores_other_files():
	other = {
		"name": "other-1.0.nvda-addon",
		"size": 5,
		"browser_download_url": f"https://github.com/{REPOSITORY}/releases/download/v0.3.0/other-1.0.nvda-addon",
	}
	notes = {"name": "notes.txt", "size": 5, "browser_download_url": "https://example.com/notes.txt"}
	release = releases.parse_release(release_json(extra_assets=[other, notes]), "mbrolaEspeak")
	assert release.package_name == "mbrolaEspeak-0.3.0.nvda-addon"


def test_parse_release_without_digest():
	assert releases.parse_release(release_json(digest=None), "mbrolaEspeak").package_sha256 is None
	assert releases.parse_release(release_json(digest="md5:abc"), "mbrolaEspeak").package_sha256 is None


@pytest.mark.parametrize(
	"data,problem",
	[
		({"assets": []}, Problem.BAD_RESPONSE),
		(["not", "a", "release"], Problem.BAD_RESPONSE),
		({"tag_name": "nightly", "assets": []}, Problem.BAD_RESPONSE),
		({"tag_name": "v0.3.0", "assets": []}, Problem.NO_PACKAGE),
		# A package hosted anywhere but this repository's releases is never used.
		(release_json(url="https://evil.example/mbrolaEspeak-0.3.0.nvda-addon"), Problem.NO_PACKAGE),
		(release_json(url="https://github.com/someone/else/releases/download/v0.3.0/x.nvda-addon"), Problem.NO_PACKAGE),
	],
)
def test_parse_release_refuses(data, problem):
	with pytest.raises(UpdateError) as caught:
		releases.parse_release(data, "mbrolaEspeak")
	assert caught.value.problem is problem


def test_parse_release_needs_a_size():
	data = release_json()
	data["assets"][0]["size"] = 0
	with pytest.raises(UpdateError, match="no size"):
		releases.parse_release(data, "mbrolaEspeak")


def test_find_update_offers_a_newer_release():
	github = FakeGitHub(release_json("v0.3.0"))
	release = releases.find_update(github.fetch_json, "0.2.0", "mbrolaEspeak")
	assert release.version == "0.3.0"
	assert github.fetched == [API_URL]


@pytest.mark.parametrize("tag", ["v0.2.0", "v0.1.0"])
def test_find_update_ignores_same_or_older_releases_even_if_broken(tag):
	github = FakeGitHub({"tag_name": tag, "assets": []})
	assert releases.find_update(github.fetch_json, "0.2.0", "mbrolaEspeak") is None


def test_find_update_with_no_release_yet():
	assert releases.find_update(FakeGitHub(None).fetch_json, "0.2.0", "mbrolaEspeak") is None


def test_find_update_reports_a_new_release_without_package():
	with pytest.raises(UpdateError) as caught:
		releases.find_update(FakeGitHub({"tag_name": "v0.3.0", "assets": []}).fetch_json, "0.2.0", "mbrolaEspeak")
	assert caught.value.problem is Problem.NO_PACKAGE


# --- downloading -------------------------------------------------------------------


def _release(**kwargs):
	return releases.parse_release(release_json(**kwargs), "mbrolaEspeak")


def _download(tmp_path, release, package):
	github = FakeGitHub(package=package)
	return download.download_package(release, tmp_path / "dl", github.open_url, "mbrolaEspeak"), github


def test_download_package(tmp_path):
	package = make_package()
	path, github = _download(tmp_path, _release(package=package), package)
	assert path == tmp_path / "dl" / "mbrolaEspeak-0.3.0.nvda-addon"
	assert path.read_bytes() == package
	assert list((tmp_path / "dl").iterdir()) == [path]  # no temporary file left behind
	assert github.opened == [_release(package=package).package_url]


def test_download_without_digest_still_checks_size_and_manifest(tmp_path):
	package = make_package()
	path, _ = _download(tmp_path, _release(package=package, digest=None), package)
	assert path.read_bytes() == package


def _assert_refused(tmp_path, release, package, problem):
	with pytest.raises(UpdateError) as caught:
		_download(tmp_path, release, package)
	assert caught.value.problem is problem
	assert not (tmp_path / "dl").exists() or list((tmp_path / "dl").iterdir()) == []


def test_download_refuses_a_short_file(tmp_path):
	package = make_package()
	_assert_refused(tmp_path, _release(package=package), package[:-10], Problem.DOWNLOAD_INCOMPLETE)


def test_download_refuses_a_long_file(tmp_path):
	package = make_package()
	_assert_refused(tmp_path, _release(package=package), package + b"extra", Problem.DOWNLOAD_INCOMPLETE)


def test_download_refuses_a_checksum_mismatch(tmp_path):
	package = make_package()
	tampered = bytearray(package)
	tampered[-1] ^= 0xFF
	_assert_refused(tmp_path, _release(package=package), bytes(tampered), Problem.CHECKSUM_MISMATCH)


def test_download_refuses_another_addon(tmp_path):
	package = make_package(name="somethingElse")
	_assert_refused(tmp_path, _release(package=package), package, Problem.WRONG_PACKAGE)


def test_download_refuses_another_version(tmp_path):
	package = make_package(version="0.2.5")
	_assert_refused(tmp_path, _release(package=package), package, Problem.WRONG_PACKAGE)


def test_download_refuses_something_that_is_not_an_addon(tmp_path):
	package = b"<html>GitHub is down</html>"
	_assert_refused(tmp_path, _release(package=package), package, Problem.WRONG_PACKAGE)


def test_download_refuses_a_foreign_address_without_connecting(tmp_path):
	release = releases.Release("0.3.0", "", "x.nvda-addon", "https://evil.example/x.nvda-addon", 10, None)
	github = FakeGitHub(package=b"x" * 10)
	with pytest.raises(UpdateError) as caught:
		download.download_package(release, tmp_path, github.open_url, "mbrolaEspeak")
	assert caught.value.problem is Problem.WRONG_PACKAGE
	assert github.opened == []


def test_download_refuses_an_oversized_package(tmp_path):
	release = _release()
	release = releases.Release(**{**release.__dict__, "package_size": download.MAX_PACKAGE_BYTES + 1})
	with pytest.raises(UpdateError, match="unreasonably large"):
		download.download_package(release, tmp_path, FakeGitHub().open_url, "mbrolaEspeak")


def test_download_network_failure_midway(tmp_path):
	class Broken(io.BytesIO):
		def read(self, size=-1):
			raise TimeoutError("timed out")

	package = make_package()
	with pytest.raises(UpdateError) as caught:
		download.download_package(_release(package=package), tmp_path / "dl", lambda url: Broken(), "mbrolaEspeak")
	assert caught.value.problem is Problem.NETWORK
	assert list((tmp_path / "dl").iterdir()) == []


# --- schedule and settings -------------------------------------------------------------

DAY = schedule.CHECK_INTERVAL_SECONDS


def test_settings_defaults_when_missing_or_broken(tmp_path):
	path = schedule.settings_path(tmp_path)
	assert path.name == "mbrolaEspeakUpdates.json"
	assert schedule.load(path) == schedule.UpdateSettings()
	path.write_text("{broken", encoding="utf-8")
	assert schedule.load(path) == schedule.UpdateSettings()
	path.write_text("[1, 2]", encoding="utf-8")
	assert schedule.load(path) == schedule.UpdateSettings()
	path.write_text('{"autoCheck": "yes", "lastCheck": true, "declinedVersion": 3}', encoding="utf-8")
	assert schedule.load(path) == schedule.UpdateSettings()


def test_settings_round_trip(tmp_path):
	path = tmp_path / "sub" / "mbrolaEspeakUpdates.json"
	settings = schedule.UpdateSettings(auto_check=False, last_check=1234.5, declined_version="0.3.0")
	schedule.save(path, settings)
	assert schedule.load(path) == settings
	assert [p.name for p in path.parent.iterdir()] == [path.name]


def test_is_due():
	settings = schedule.UpdateSettings(last_check=10 * DAY)
	assert not settings.is_due(10 * DAY + DAY - 1)
	assert settings.is_due(11 * DAY)
	assert settings.is_due(9 * DAY)  # the clock went backwards
	assert schedule.UpdateSettings().is_due(DAY)  # never checked
	assert not schedule.UpdateSettings(auto_check=False).is_due(100 * DAY)


def test_declined_version_is_only_hidden_from_automatic_checks():
	settings = schedule.UpdateSettings(declined_version="0.3.0")
	assert not settings.should_offer("0.3.0", automatic=True)
	assert settings.should_offer("0.3.0", automatic=False)
	assert settings.should_offer("0.4.0", automatic=True)


# --- messages ------------------------------------------------------------------------


def _french():
	po = i18n.po_files()["fr"]
	return gettext.GNUTranslations(io.BytesIO(i18n.compile_po_file(po))).gettext


@pytest.mark.parametrize("translate", [lambda s: s, _french()], ids=["en", "fr"])
def test_every_problem_has_a_complete_message(translate):
	m = UpdateMessages(translate)
	for problem in Problem:
		text = m.download_failed(UpdateError(problem, "detail"))
		assert "{" not in text and text.strip()
		assert m.reason(UpdateError(problem, "detail")) in text
	assert len({m.reason(UpdateError(p, "d")) for p in Problem}) == len(Problem)


def test_offer_messages():
	release = _release()
	m = UpdateMessages()
	manual = m.offer(release, "0.2.0", automatic=False)
	assert manual.startswith("Version 0.3.0 of the eSpeak NG with MBROLA add-on is available. You have version 0.2.0.")
	assert "will not be offered again" not in manual
	assert "will not be offered again when NVDA starts" in m.offer(release, "0.2.0", automatic=True)
	assert m.up_to_date("0.2.0") == "You have the latest version of the eSpeak NG with MBROLA add-on (0.2.0)."


def test_offer_in_french():
	m = UpdateMessages(_french())
	assert m.offer(_release(), "0.2.0", automatic=False).startswith(
		"La version 0.3.0 de l'extension eSpeak NG avec MBROLA est disponible. Vous avez la version 0.2.0.",
	)
	assert m.check_failed(UpdateError(Problem.NETWORK, "timed out")) == (
		"Impossible de rechercher les mises à jour de l'extension MBROLA. Impossible de joindre GitHub (timed out)."
	)
	assert m.title == "Mise à jour de l'extension MBROLA"


# --- HTTP (against a local server; nothing goes online) ------------------------------------


class _Handler(http.server.BaseHTTPRequestHandler):
	routes: dict = {}
	seen: list = []

	def do_GET(self):
		_Handler.seen.append((self.path, self.headers.get("User-Agent"), self.headers.get("Accept")))
		status, body = _Handler.routes.get(self.path, (404, b"{}"))
		self.send_response(status)
		self.send_header("Content-Length", str(len(body)))
		self.end_headers()
		self.wfile.write(body)

	def log_message(self, *args):
		pass


@pytest.fixture
def local_server():
	_Handler.routes, _Handler.seen = {}, []
	server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
	thread = threading.Thread(target=server.serve_forever, daemon=True)
	thread.start()
	yield f"http://127.0.0.1:{server.server_port}"
	server.shutdown()
	server.server_close()


def test_fetch_json(local_server):
	_Handler.routes = {
		"/ok": (200, json.dumps({"tag_name": "v1.0.0"}).encode()),
		"/broken": (200, b"<html>"),
		"/error": (500, b""),
	}
	fetch = web.make_json_fetcher("0.2.0", timeout=5)
	assert fetch(local_server + "/ok") == {"tag_name": "v1.0.0"}
	assert _Handler.seen[0] == ("/ok", "mbrolaEspeak-NVDA-addon/0.2.0", "application/vnd.github+json")
	assert fetch(local_server + "/missing") is None
	with pytest.raises(UpdateError) as caught:
		fetch(local_server + "/error")
	assert caught.value.problem is Problem.NETWORK and "500" in caught.value.detail
	with pytest.raises(UpdateError) as caught:
		fetch(local_server + "/broken")
	assert caught.value.problem is Problem.BAD_RESPONSE


def test_fetch_json_unreachable():
	fetch = web.make_json_fetcher("0.2.0", timeout=2)
	with pytest.raises(UpdateError) as caught:
		fetch("http://127.0.0.1:9/")  # the discard port: nothing listens there
	assert caught.value.problem is Problem.NETWORK


def test_downloads_must_stay_on_https(local_server):
	_Handler.routes = {"/package": (200, b"data")}
	with pytest.raises(UpdateError, match="HTTPS"):
		web.make_opener("0.2.0", timeout=5)(local_server + "/package")
