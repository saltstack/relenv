# Copyright 2025 Broadcom.
# SPDX-License-Identifier: Apache-2.0
#
from __future__ import annotations

import importlib
import pathlib
from typing import TYPE_CHECKING, Any, Callable, List, Sequence, TypeVar, cast

import pytest

if TYPE_CHECKING:
    from _pytest.mark.structures import ParameterSet

F = TypeVar("F", bound=Callable[..., object])


def typed_parametrize(*args: Any, **kwargs: Any) -> Callable[[F], F]:
    """Type-aware wrapper around pytest.mark.parametrize."""
    decorator = pytest.mark.parametrize(*args, **kwargs)
    return cast(Callable[[F], F], decorator)


def _top_level_modules() -> Sequence["ParameterSet"]:
    relenv_dir = pathlib.Path(__file__).resolve().parents[1] / "relenv"
    params: List["ParameterSet"] = []
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


@typed_parametrize("module_name", _top_level_modules())
def test_import_top_level_module(module_name: str) -> None:
    """
    Ensure each top-level module in the relenv package can be imported.
    """
    importlib.import_module(module_name)
