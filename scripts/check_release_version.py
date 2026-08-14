"""Verify a release tag matches the version declared in pyproject.toml.

Used by the release workflow as a guard: a GitHub Release tagged ``vX.Y.Z`` must
correspond to ``version = "X.Y.Z"`` in pyproject.toml, otherwise the build would
publish the wrong (or a duplicate) version to PyPI.

Reads the version with a regex rather than a TOML parser so it runs unchanged on
Python 3.10 (no ``tomllib``).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_VERSION_RE = re.compile(r'(?m)^\s*version\s*=\s*"([^"]+)"')

# pyproject.toml lives at the repo root, one level up from scripts/.
DEFAULT_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def normalize_tag(tag: str) -> str:
    """Strip surrounding whitespace and a leading ``v`` from a release tag."""
    tag = tag.strip()
    if tag.startswith("v"):
        tag = tag[1:]
    return tag


def read_pyproject_version(path: Path | str = DEFAULT_PYPROJECT) -> str:
    """Return the ``version`` string from a pyproject.toml. Raises ValueError if
    no version field is present."""
    text = Path(path).read_text(encoding="utf-8")
    match = _VERSION_RE.search(text)
    if not match:
        raise ValueError(f"No version field found in {path}")
    return match.group(1)


def tag_matches(tag: str, version: str) -> bool:
    return normalize_tag(tag) == version.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", help="Release tag, e.g. v0.4.2")
    parser.add_argument(
        "--pyproject",
        default=str(DEFAULT_PYPROJECT),
        help="Path to pyproject.toml (defaults to repo root)",
    )
    args = parser.parse_args(argv)

    version = read_pyproject_version(args.pyproject)
    if not tag_matches(args.tag, version):
        print(
            f"ERROR: release tag {args.tag!r} (normalized {normalize_tag(args.tag)!r}) "
            f"does not match pyproject version {version!r}. "
            "Bump the version before cutting the release.",
            file=sys.stderr,
        )
        return 1
    print(f"OK: tag {args.tag} matches pyproject version {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
