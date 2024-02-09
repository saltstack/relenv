# Copyright 2023-2024 VMware, Inc.
# SPDX-License-Identifier: Apache-2.0
#
import importlib
import sys

import relenv.runtime


def test_importer():
    def mywrapper(name):
        mod = importlib.import_module(name)
        mod.__test_case__ = True
        return mod

    importer = relenv.runtime.RelenvImporter(
        wrappers=[
            relenv.runtime.Wrapper("pip._internal.locations", mywrapper),
        ]
    )

    sys.meta_path = [importer] + sys.meta_path

    import pip._internal.locations

    assert hasattr(pip._internal.locations, "__test_case__")
    assert pip._internal.locations.__test_case__ is True
