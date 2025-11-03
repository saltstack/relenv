# Copyright 2022-2025 Broadcom.
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import sys

from relenv.common import __version__

MIN_SUPPORTED_PYTHON = (3, 10)

if sys.version_info < MIN_SUPPORTED_PYTHON:
    raise RuntimeError("Relenv requires Python 3.10 or newer.")


__all__ = ["__version__"]
