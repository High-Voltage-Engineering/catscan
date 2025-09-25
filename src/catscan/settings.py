from enum import IntEnum
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from .utils import typeutil, yamlutil


class CheckLevel(IntEnum):
    ERROR = 0  # will cause the linter to fail
    WARNING = 1  # will be logged, but will not cause failure
    INFO = 2  # will be logged if the global linter level is set to INFO or lower
    FINE = 3  # will be logged if the global linter level is set to FINE


class CheckSettings(BaseModel):
    enabled: bool = True
    level: typeutil.friendly_enum(CheckLevel) = CheckLevel.ERROR


def _to_set(value: Any) -> set:
    if isinstance(value, list):
        return set(value)
    if not isinstance(value, set):
        return {value}
    return value


class Settings(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )

    level: typeutil.friendly_enum(CheckLevel) = CheckLevel.WARNING
    checks: dict[str, CheckSettings] = Field(
        default_factory=dict,
        description="Per-check settings",
    )
    builtin_symbols: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Mapping of built-in symbols and their types. If a 'variable' is actually"
            "of 'type' type, use <type> so it will not be matched by anything else. This is"
            "used to detect 'unknown' symbols."
        ),
    )
    builtin_functions: list[str] = Field(
        default_factory=list,
        description="List of built-in functions like MEMCPY, MEMMOVE, etc.",
    )
    block_prefixes: dict[str, Annotated[set[str], BeforeValidator(_to_set)]] = Field(
        default_factory=dict,
        description="Prefixes for blocks (i.e. VAR_INPUT -> i_, VAR -> ['', 'ps_']",
    )
    type_prefixes: dict[str, str] = Field(
        default_factory=dict,
        description="Prefixes for types (i.e. BOOL -> b, INT -> n, ...)",
    )
    function_block_prefix: str | None = Field(
        default=None,
        description="Prefix for (registered) function block types",
    )
    interface_prefix: str | None = Field(
        default=None,
        description="Prefix for (registered) interface types",
    )
    enum_prefix: str | None = Field(
        default=None,
        description="Prefix for (registered) enum types",
    )
    struct_prefix: str | None = Field(
        default=None,
        description="Prefix for (registered) struct types",
    )
    reference_prefix: str | None = Field(
        default=None,
        description="Prefix for reference types",
    )
    array_prefix: str | None = Field(
        default=None,
        description="Prefix for array types",
    )
    max_nameless_args: int = Field(
        default=3,
        description=(
            "Maximum amount of nameless arguments allowed in a function call, before all input"
            "arguments have to be named explicitly"
        ),
    )
    nameless_arg_functions: set[str] = Field(
        default_factory=set,
        description="Set of functions which are allowed to have unnamed arguments",
    )
    nameless_arg_methods: set[str | tuple[str, str]] = Field(
        default_factory=set,
        description=(
            "Set of method names or (type, method) pairs "
            "which are allowed to have unnamed arguments"
        ),
    )


def load_settings(file: Path | None) -> Settings:
    if file is not None:
        return yamlutil.load(file, as_type=Settings)
    return Settings()
