from enum import IntEnum
from functools import partial
from typing import Annotated, Any, TypeVar

from pydantic import BeforeValidator

_E = TypeVar("_E", bound=IntEnum)


def cast_to_enum(enum_t: type[_E], value: Any):
    if isinstance(value, enum_t):
        return value

    if isinstance(value, str):
        return enum_t[value]

    if isinstance(value, int):
        return enum_t(value)

    msg = f"Could not convert {value=} to {enum_t=}"
    raise ValueError(msg)


def friendly_enum(enum_t: type[_E]) -> type[_E]:
    return Annotated[enum_t, BeforeValidator(partial(cast_to_enum, enum_t))]
