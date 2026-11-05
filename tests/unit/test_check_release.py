import check_release
import pytest
from update_fixtures import make_package


@pytest.fixture
def package(tmp_path):
	def make(file_name="mbrolaEspeak-0.3.0.nvda-addon", version="0.3.0"):
		path = tmp_path / file_name
		path.write_bytes(make_package(version=version))
		return path

	return make


def test_matching_tag_and_package(package):
	assert check_release.check("v0.3.0", package()) == []
	assert check_release.main(["v0.3.0", str(package())]) == 0


@pytest.mark.parametrize("tag", ["0.3.0", "v0.3", "v0.3.0-rc1", "release"])
def test_tag_must_be_a_plain_version(package, tag):
	assert "is not of the form v1.2.3" in check_release.check(tag, package())[0]


def test_tag_and_manifest_must_agree(package):
	errors = check_release.check("v0.3.0", package(file_name="mbrolaEspeak-0.3.0.nvda-addon", version="0.2.0"))
	assert errors[0] == "tag v0.3.0 but the package manifest says version '0.2.0'"


def test_file_name_must_match(package):
	errors = check_release.check("v0.3.0", package(file_name="addon.nvda-addon"))
	assert errors == ["package file is addon.nvda-addon, expected mbrolaEspeak-0.3.0.nvda-addon"]


def test_unreadable_package(tmp_path):
	bad = tmp_path / "mbrolaEspeak-0.3.0.nvda-addon"
	bad.write_bytes(b"not a zip")
	assert "not a readable add-on package" in check_release.check("v0.3.0", bad)[0]
	assert check_release.main(["v0.3.0", str(bad)]) == 1
