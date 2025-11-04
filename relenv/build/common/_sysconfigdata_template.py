# Copyright 2022-2025 Broadcom.
# SPDX-License-Identifier: Apache-2.0
# mypy: ignore-errors
# flake8: noqa
"""
Template for sysconfigdata module generated at build time.

This file is used as a template to generate the _sysconfigdata module
that CPython uses at runtime. It is copied verbatim (after the header comments)
into the generated sysconfigdata file.

The _build_time_vars dictionary is written before this content.

Note: mypy and flake8 errors are ignored for this template file as it contains
code that is valid only in the context of the generated sysconfigdata module
(e.g., _build_time_vars is injected, RelenvException is in generated context).
"""

import pathlib
import sys
import platform
import os
import logging

log = logging.getLogger(__name__)


def build_arch():
    machine = platform.machine()
    return machine.lower()


def get_triplet(machine=None, plat=None):
    if not plat:
        plat = sys.platform
    if not machine:
        machine = build_arch()
    if plat == "darwin":
        return f"{machine}-macos"
    elif plat == "win32":
        return f"{machine}-win"
    elif plat == "linux":
        return f"{machine}-linux-gnu"
    else:
        raise RelenvException("Unknown platform {}".format(platform))


pydir = pathlib.Path(__file__).resolve().parent
if sys.platform == "win32":
    DEFAULT_DATA_DIR = pathlib.Path.home() / "AppData" / "Local" / "relenv"
else:
    DEFAULT_DATA_DIR = pathlib.Path.home() / ".local" / "relenv"

if "RELENV_DATA" in os.environ:
    DATA_DIR = pathlib.Path(os.environ["RELENV_DATA"]).resolve()
else:
    DATA_DIR = DEFAULT_DATA_DIR

buildroot = pydir.parent.parent

toolchain = DATA_DIR / "toolchain" / get_triplet()

build_time_vars = {}
for key in _build_time_vars:
    val = _build_time_vars[key]
    orig = val
    if isinstance(val, str):
        val = val.format(
            BUILDROOT=buildroot,
            TOOLCHAIN=toolchain,
        )
    build_time_vars[key] = val
