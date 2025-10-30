# Copyright 2025 Broadcom.
# SPDX-License-Identifier: Apache-2.0
#
import importlib
import pathlib

import pytest


def _top_level_modules():
    relenv_dir = pathlib.Path(__file__).resolve().parents[1] / "relenv"
    params = []
    for path in sorted(relenv_dir.iterdir()):
        if not path.is_file() or path.suffix != ".py":
            continue
        stem = path.stem
        if stem == "__init__":
            module_name = "relenv"
        else:
            module_name = f"relenv.{stem}"
        params.append(pytest.param(module_name, id=module_name))
    return params


@pytest.mark.parametrize("module_name", _top_level_modules())
def test_import_top_level_module(module_name: str) -> None:
    """
    Ensure each top-level module in the relenv package can be imported.
    """
    importlib.import_module(module_name)
