import textwrap

import check_release_version as crv
import pytest


def test_normalize_tag_strips_leading_v():
    assert crv.normalize_tag("v0.4.2") == "0.4.2"
    assert crv.normalize_tag("0.4.2") == "0.4.2"
    assert crv.normalize_tag("  v1.2.3  ") == "1.2.3"


def test_tag_matches():
    assert crv.tag_matches("v0.4.2", "0.4.2") is True
    assert crv.tag_matches("0.4.2", "0.4.2") is True
    assert crv.tag_matches("v0.5.0", "0.4.2") is False


def test_read_pyproject_version(tmp_path):
    p = tmp_path / "pyproject.toml"
    p.write_text(
        textwrap.dedent(
            """
            [build-system]
            requires = ["setuptools>=68"]

            [project]
            name = "google-analytics-agent"
            version = "1.2.3"
            description = "x"
            """
        )
    )
    assert crv.read_pyproject_version(p) == "1.2.3"


def test_read_pyproject_version_missing_raises(tmp_path):
    p = tmp_path / "pyproject.toml"
    p.write_text("[project]\nname = 'x'\n")
    with pytest.raises(ValueError):
        crv.read_pyproject_version(p)


def test_main_ok(tmp_path, capsys):
    p = tmp_path / "pyproject.toml"
    p.write_text('[project]\nname = "x"\nversion = "0.4.2"\n')
    rc = crv.main(["v0.4.2", "--pyproject", str(p)])
    assert rc == 0


def test_main_mismatch(tmp_path, capsys):
    p = tmp_path / "pyproject.toml"
    p.write_text('[project]\nname = "x"\nversion = "0.4.2"\n')
    rc = crv.main(["v0.5.0", "--pyproject", str(p)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "0.5.0" in err and "0.4.2" in err
