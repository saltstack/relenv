# Copyright 2022-2025 Broadcom.
# SPDX-License-Identifier: Apache-2.0
"""
Build process common methods.

This module has been split into focused submodules for better organization.
All public APIs are re-exported here for backward compatibility.
"""
from __future__ import annotations

from .builders import (
    build_openssl,
    build_openssl_fips,
    build_sqlite,
)

from .install import (
    update_ensurepip,
    install_runtime,
    finalize,
    create_archive,
    patch_file,
)

from .builder import (
    Dirs,
    builds,
    get_dependency_version,
)


__all__ = [
    # Builder classes and instances
    "Dirs",
    "builds",
    # Dependency version management
    "get_dependency_version",
    # Install functions
    "finalize",
    "install_runtime",
    "create_archive",
    "update_ensurepip",
    "patch_file",
    # Builders (specific build functions)
    "build_openssl",
    "build_openssl_fips",
    "build_sqlite",
]
