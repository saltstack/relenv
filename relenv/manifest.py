# Copyright 2022-2026 Broadcom.
# SPDX-License-Identifier: Apache-2.0
#
"""
Relenv manifest.
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import sys


def manifest(root: str | os.PathLike[str] | None = None) -> None:
    """
    List all the file in a relenv and their hashes.
    """
    base = (
        pathlib.Path(root)
        if root is not None
        else pathlib.Path(getattr(sys, "RELENV", os.getcwd()))
    )
    for dirpath, _dirs, files in os.walk(base):
        directory = pathlib.Path(dirpath)
        for file in files:
            hsh = hashlib.sha256()
            file_path = directory / file
            try:
                with open(file_path, "rb") as fp:
                    while True:
                        chunk = fp.read(9062)
                        if not chunk:
                            break
                        hsh.update(chunk)
            except OSError:
                pass
            print(f"{file_path} => {hsh.hexdigest()}")


if __name__ == "__main__":
    manifest()
