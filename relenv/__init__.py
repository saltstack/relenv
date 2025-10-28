# Copyright 2025 Broadcom.
# SPDX-License-Identifier: Apache-2
import sys

if sys.version_info < (3, 10):
    raise RuntimeError("Relenv requires Python 3.10 or newer.")

from relenv.common import __version__
