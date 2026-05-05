#!/usr/bin/env python3
# Copyright 2021-2026 Broadcom.
# SPDX-License-Identifier: Apache-2.0
#
# pylint: skip-file
import argparse
import pathlib
import re
import sys

CODE_ROOT = pathlib.Path(__file__).resolve().parent.parent
CHANGELOG_ENTRIES_PATH = CODE_ROOT / "changelog"
CHANGELOG_LIKE_RE = re.compile(r"([\d]+)\.([a-z]+)(\.rst)?$")
CHANGELOG_EXTENSIONS = (
    "breaking",
    "deprecation",
    "feature",
    "improvement",
    "bugfix",
    "doc",
    "trivial",
)
CHANGELOG_ENTRY_REREX = r"^[\d]+\.({})\.rst$".format("|".join(CHANGELOG_EXTENSIONS))
CHANGELOG_ENTRY_RE = re.compile(CHANGELOG_ENTRY_REREX)


def check_changelog_entries(files):
    exitcode = 0
    for entry in files:
        path = pathlib.Path(entry).resolve()
        # Is it under changelog/
        try:
            path.relative_to(CHANGELOG_ENTRIES_PATH)
            if path.name in (".gitignore", "_template.rst", __name__):
                # These files should be ignored
                continue
            # Is it named properly
            if not CHANGELOG_ENTRY_RE.match(path.name):
                # Does it end in .rst
                if path.suffix != ".rst":
                    exitcode = 1
                    msg = (
                        f"The changelog entry '{path.relative_to(CODE_ROOT)}' should have '.rst' as it's file extension"
                    )
                    print(msg, file=sys.stderr, flush=True)
                    continue
                print(
                    "The changelog entry '{}' should have one of the following extensions: {}.".format(
                        path.relative_to(CODE_ROOT),
                        ", ".join(repr(ext) for ext in CHANGELOG_EXTENSIONS),
                    ),
                    file=sys.stderr,
                    flush=True,
                )
                exitcode = 1
                continue
            check_changelog_entry_contents(path)
        except ValueError:
            # Not under changelog/, carry on checking
            # Is it a changelog entry
            if CHANGELOG_ENTRY_RE.match(path.name):
                # So, this IS a changelog entry, but it's misplaced....
                exitcode = 1
                msg = (
                    f"The changelog entry '{path.relative_to(CODE_ROOT)}' "
                    f"should be placed under '{CHANGELOG_ENTRIES_PATH.relative_to(CODE_ROOT)}/', "
                    f"not '{path.relative_to(CODE_ROOT).parent}'"
                )
                print(msg, file=sys.stderr, flush=True)
                continue
            elif CHANGELOG_LIKE_RE.match(path.name) and not CHANGELOG_ENTRY_RE.match(path.name):
                # Does it look like a changelog entry
                print(
                    "The changelog entry '{}' should have one of the following extensions: {}.".format(
                        path.relative_to(CODE_ROOT),
                        ", ".join(repr(ext) for ext in CHANGELOG_EXTENSIONS),
                    ),
                    file=sys.stderr,
                    flush=True,
                )
                exitcode = 1
                continue

            elif not CHANGELOG_LIKE_RE.match(path.name) and not CHANGELOG_ENTRY_RE.match(path.name):
                # Does not look like, and it's not a changelog entry
                continue
            # Does it end in .rst
            if path.suffix != ".rst":
                exitcode = 1
                print(
                    f"The changelog entry '{path.relative_to(CODE_ROOT)}' should have '.rst' as it's file extension",
                    file=sys.stderr,
                    flush=True,
                )
    return exitcode


def check_changelog_entry_contents(entry):
    contents = entry.read_text().splitlines()
    if len(contents) > 1:
        if contents[1].strip() and contents[1].strip()[0] not in ("-", "=", "~", "^", "*", "+", "#", "<", ">"):
            # This is not a heading
            print(
                f"The changelog entry '{entry.relative_to(CODE_ROOT)}' should have a heading.",
                file=sys.stderr,
                flush=True,
            )
            sys.exit(1)


def main(argv):
    parser = argparse.ArgumentParser(prog=__name__)
    parser.add_argument("files", nargs="+")
    args = parser.parse_args(argv)
    return check_changelog_entries(args.files)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
