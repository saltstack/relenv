#!/usr/bin/env python3
"""
Prepare an automated release PR.

Given the pre-update and post-update copies of ``relenv/python-versions.json``,
this script:

1. Computes a human-readable list of changelog bullets describing what
   versions were added or bumped.
2. Bumps the patch component of ``__version__`` in ``relenv/common.py``.
3. Prepends a new section to ``CHANGELOG.md`` containing the bullets.

Run from the repo root::

    python3 .github/scripts/prepare_release_pr.py <before.json> <after.json>

Exits 0 with no changes if no relevant additions were detected.
"""
import json
import re
import sys
from pathlib import Path

from packaging.version import InvalidVersion, Version


def _load(path):
    with open(path) as f:
        return json.load(f)


def _best(versions):
    try:
        return max(versions, key=Version)
    except InvalidVersion:
        return sorted(versions)[-1]


def python_bullets(before, after):
    before_py = before.get("python", {})
    after_py = after.get("python", {})

    added_by_minor = {}
    for ver in set(after_py) - set(before_py):
        parts = ver.split(".")
        if len(parts) < 3:
            continue
        minor = f"{parts[0]}.{parts[1]}"
        added_by_minor.setdefault(minor, []).append(ver)

    bullets = []
    for minor in sorted(added_by_minor, key=Version):
        new_top = _best(added_by_minor[minor])
        had_minor = any(v.startswith(f"{minor}.") for v in before_py)
        if had_minor:
            bullets.append(f"* Update python {minor} to {new_top}")
        else:
            bullets.append(f"* Add python {new_top}")
    return bullets


def dep_bullets(before, after):
    before_deps = before.get("dependencies", {})
    after_deps = after.get("dependencies", {})

    bullets = []
    for dep in sorted(after_deps):
        new = set(after_deps[dep]) - set(before_deps.get(dep, {}))
        if not new:
            continue
        bullets.append(f"* Update {dep} to {_best(new)}")
    return bullets


def bump_patch(version_str):
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)$", version_str)
    if not m:
        raise ValueError(f"Cannot bump version {version_str!r}: expected X.Y.Z")
    major, minor, patch = (int(x) for x in m.groups())
    return f"{major}.{minor}.{patch + 1}"


def update_version_file(path):
    text = path.read_text()
    m = re.search(r'^__version__ = "([^"]+)"', text, re.MULTILINE)
    if not m:
        raise RuntimeError(f"Could not find __version__ in {path}")
    current = m.group(1)
    new = bump_patch(current)
    path.write_text(text[: m.start(1)] + new + text[m.end(1) :])
    return current, new


def prepend_changelog(path, version, bullets):
    header = f"{version}\n{'=' * len(version)}\n\n"
    body = "\n".join(bullets) + "\n\n\n"
    path.write_text(header + body + path.read_text())


def main(argv):
    if len(argv) != 3:
        print(f"usage: {argv[0]} <before.json> <after.json>", file=sys.stderr)
        return 2

    before = _load(argv[1])
    after = _load(argv[2])

    bullets = python_bullets(before, after) + dep_bullets(before, after)
    if not bullets:
        print("No version changes detected.", file=sys.stderr)
        return 0

    _, new_version = update_version_file(Path("relenv/common.py"))
    prepend_changelog(Path("CHANGELOG.md"), new_version, bullets)

    print(new_version)
    for bullet in bullets:
        print(bullet)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
