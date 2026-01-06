# Copyright 2022-2026 Broadcom.
# SPDX-License-Identifier: Apache-2.0
"""
Typed helper wrappers for common pytest decorators so mypy understands them.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, Sequence, TypeVar, cast

import pytest

F = TypeVar("F", bound=Callable[..., object])


def fixture(*args: Any, **kwargs: Any) -> Callable[[F], F] | F:
    if args and callable(args[0]) and not kwargs:
        func = cast(F, args[0])
        return cast(F, pytest.fixture()(func))

    def decorator(func: F) -> F:
        wrapped = pytest.fixture(*args, **kwargs)(func)
        return cast(F, wrapped)

    return decorator


def mark_skipif(*args: Any, **kwargs: Any) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        wrapped = pytest.mark.skipif(*args, **kwargs)(func)
        return cast(F, wrapped)

    return decorator


def parametrize(
    argnames: str | Sequence[str],
    argvalues: Iterable[Sequence[Any] | Any],
    *args: Any,
    **kwargs: Any,
) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        wrapped = pytest.mark.parametrize(argnames, argvalues, *args, **kwargs)(func)
        return cast(F, wrapped)

    return decorator
