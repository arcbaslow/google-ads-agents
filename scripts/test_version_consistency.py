"""The version is declared in three places. They have to agree.

pyproject.toml and .claude-plugin/plugin.json both sat at 0.1.0 through
the 0.2.0-0.6.0 releases because nothing checked them. This test is the
check.
"""

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_VERSION_RE = re.compile(r'(?m)^\s*version\s*=\s*"([^"]+)"')


def _pyproject_version():
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = _VERSION_RE.search(text)
    assert match, "no version field in pyproject.toml"
    return match.group(1)


def _plugin_version():
    text = (REPO_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    return json.loads(text)["version"]


def _changelog_latest():
    """First `## <version>` heading in CHANGELOG.md, skipping `## Unreleased`."""
    for line in (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines():
        if not line.startswith("## "):
            continue
        heading = line[3:].strip().strip("[]")
        if heading.lower() == "unreleased":
            continue
        # Handles both "## 0.5.1 - date" and the bracketed
        # "## [1.0.1] - date" Keep a Changelog form.
        return heading.split()[0].strip("[]").lstrip("v")
    raise AssertionError("no released version heading in CHANGELOG.md")


def test_plugin_matches_pyproject():
    assert _plugin_version() == _pyproject_version()


def test_pyproject_matches_changelog():
    assert _pyproject_version() == _changelog_latest()
