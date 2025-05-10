# Copyright 2025 Broadcom.
# SPDX-License-Identifier: Apache-2.0
#
"""
Relenv manifest.
"""
import hashlib
import os
import sys


def manifest(root=None):
    """
    List all the file in a relenv and their hashes.
    """
    if root is None:
        root = getattr(sys, "RELENV", os.getcwd())
    for root, dirs, files in os.walk(root):
        for file in files:
            hsh = hashlib.sha256()
            try:
                with open(root + os.path.sep + file, "rb") as fp:
                    while True:
                        chunk = fp.read(9062)
                        if not chunk:
                            break
                        hsh.update(chunk)
            except OSError:
                pass
            print(f"{root + os.path.sep + file} => {hsh.hexdigest()}")


if __name__ == "__main__":
    manifest()
