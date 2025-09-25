import re
from typing import Any, TypeVar

import blark.transform as tf
from blark.summary import DeclarationSummary, FunctionBlockSummary, MethodSummary

from . import log

logger = log.get_logger()

_T = TypeVar("_T")

# https://infosys.beckhoff.com/english.php?content=../content/1033/tf5100_tc3_nc_i/4188351883.html&id=
# NOTE: there are ORDERED by size, which is important for finding the common types of two
# different arithmetic types
BUILTIN_BITSTRINGS = (
    "BOOL",
    "BYTE",
    "WORD",
    "DWORD",
    "LWORD",
)

BUILTIN_UNSIGNED_INTEGERS = (
    "USINT",
    "UINT",
    "UDINT",
    "ULINT",
)

BUILTIN_SIGNED_INTEGERS = (
    "SINT",
    "INT",
    "DINT",
    "LINT",
)

BUILTIN_FLOATING_POINT = (
    "REAL",
    "LREAL",
)

BUILTIN_TIME_RELATED = (
    "TIME",
    "LTIME",
    "DATE",
    "LDATE",
    "TIME_OF_DAY",
    "TOD",
    "LTIME_OF_DAY",
    "LTOD",
    "DATE_AND_TIME",
    "DT",
    "LDATE_AND_TIME",
    "LDT",
)

# todo: builtin string / char types

# NOTE: these should not contain strings:
# https://infosys.beckhoff.com/english.php?content=../content/1033/tc3_plc_intro/3998090635.html&id=
BUILTIN_ELEMENTARY_TYPES = (
    *BUILTIN_BITSTRINGS,
    *BUILTIN_UNSIGNED_INTEGERS,
    *BUILTIN_SIGNED_INTEGERS,
    *BUILTIN_FLOATING_POINT,
    *BUILTIN_TIME_RELATED,
)

BUILTIN_TYPE_CONVERSIONS = {
    f"{from_t}_TO_{to_t}": to_t
    for from_t in BUILTIN_ELEMENTARY_TYPES
    for to_t in BUILTIN_ELEMENTARY_TYPES
    if from_t != to_t
} | {f"TO_{to_t}": to_t for to_t in BUILTIN_ELEMENTARY_TYPES}

BUILTIN_FUNCTIONS = {
    "LEN": "INT",
    "FIND": "INT",
    "TRUNC": "DINT",  # LREAL -> DINT
    "TRUNC_INT": "INT",  # REAL -> INT
    "SIZEOF": "USINT",  # May actually return UINT / UDINT / ULINT depending on the actual value
}


def common_arithmetic_type(typ1: str | None, typ2: str | None) -> str | None:
    """Determine common type for two arithmetic types as best we can. Either type may be
    unknown, in which case we just return the other."""
    if typ1 is None:
        return typ2
    if typ2 is None:
        return typ1
    if typ1 == typ2:
        # Oh, I know this one!
        return typ1

    # dominance of types in order
    dominant_types = [
        BUILTIN_TIME_RELATED,
        BUILTIN_FLOATING_POINT,
        BUILTIN_UNSIGNED_INTEGERS,
        BUILTIN_SIGNED_INTEGERS,
    ]
    for typset in dominant_types:
        if typ1 in typset and typ2 not in typset:
            return typ1
        if typ2 in typset and typ1 not in typset:
            return typ2
        if typ1 in typset and typ2 in typset:
            # higher index is larger type
            return typset[max(typset.index(typ1), typset.index(typ2))]

    logger.warning(f"Failed to determine common type of arithmetic types {typ1} and {typ2}")
    # just return either as best guess?
    return typ1 or typ2


def streq(s1: str, s2: str) -> bool:
    """Non-strict string comparison"""
    return str(s1).lower() == str(s2).lower()


def is_super(var: str) -> bool:
    return streq(var, "SUPER") or streq(var, "SUPER^")


def is_super_call(stat: tf.Statement, meth: str):
    return (
        isinstance(stat, tf.FunctionCall)
        and isinstance(stat.name, tf.MultiElementVariable)
        and is_super(stat.name.name.name)  # SUPER.<something>
        and len(stat.name.elements) == 1
        and isinstance(stat.name.elements[0], tf.FieldSelector)
        and streq(stat.name.elements[0].field.name, meth)
    )


def is_abstract(obj: FunctionBlockSummary | MethodSummary) -> bool:
    return ((obj.item.access or 0) & tf.AccessSpecifier.abstract) != 0


def has_case_insensitive(
    coll: dict[str, Any] | set[str],
    key: str,
) -> bool:
    """Check whether a dictionary or set of strings contains a string case-insensitively."""
    if key in coll:
        return True
    for k in coll:
        if streq(k, key):
            return True
    return False


def get_case_insensitive_with_fixed_key(
    dct: dict[str, _T],
    key: str,
    default: _T | None = None,
) -> tuple[str | None, _T | None]:
    """Get case-insensitive key from a dictionary, with default. Useful because TwinCAT is
    case-insensitive. Also return the 'fixed' key."""
    if key in dct:
        return key, dct[key]
    if key is None:
        return None, default
    for k, v in dct.items():
        if streq(k, key):
            return k, v
    return None, default


def get_case_insensitive(
    dct: dict[str, _T],
    key: str,
    default: _T | None = None,
) -> _T | None:
    """Get case-insensitive key from a dictionary, with default. Useful because TwinCAT is
    case-insensitive."""
    return get_case_insensitive_with_fixed_key(dct, key, default=default)[1]


ARRAY_TYPE_RE = re.compile(r"^ARRAY\s*\[([^]]*)]\s*OF\s+(.*)\s*$")
REFERENCE_TYPE_RE = re.compile(r"^REFERENCE TO (.*)$")


def is_array(typ: str) -> bool:
    return ARRAY_TYPE_RE.match(typ) is not None


def get_array_dims_and_base_type(arr: str) -> tuple[int, str]:
    match = ARRAY_TYPE_RE.match(arr)
    dims = match.group(1).count(",")
    return dims, match.group(2)


def is_reference(typ: str) -> bool:
    return REFERENCE_TYPE_RE.match(typ) is not None


def get_reference_base_type(typ: str) -> str:
    match = REFERENCE_TYPE_RE.match(typ)
    return match.group(1)


def is_call_to(expr: tf.Expression, func_name: str) -> bool:
    """Check whether an expression is a call to a function by the name 'func_name'"""
    return (
        isinstance(expr, tf.FunctionCall)
        and isinstance(expr.name, tf.SimpleVariable)
        and streq(expr.name.name, func_name)
    )


def decl_is_initialized(decl: DeclarationSummary) -> bool:
    """Check whether declaration initializes the declared variable"""
    if streq(decl.block, "VAR_INPUT"):
        # input variables are always initialized (as they are passed externally)
        return True
    if streq(decl.block, "VAR_INST"):
        # static variables are assumed to be initialized
        return True
    return getattr(getattr(decl.item, "init", None), "value", None) is not None
