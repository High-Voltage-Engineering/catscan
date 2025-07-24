import re

import blark.transform as tf
from blark.summary import (
    DeclarationSummary,
)

from catscan.lint.base import lint_check
from catscan.lint.context import Context
from catscan.lint.error import ErrorInfo
from catscan.settings import Settings
from catscan.utils import log, tc3
from catscan.utils.program import (
    get_expressions,
    get_subexpressions,
    has_assignment_before,
    is_assignment_for,
)
from catscan.utils.tc3 import (
    get_array_dims_and_base_type,
    get_reference_base_type,
    is_array,
    is_reference,
)

logger = log.get_logger()


@lint_check("VAR000")
def invalid_scoping(expr: tf.SimpleVariable, ctx: Context):
    """Check if variable can be found in the context. If not, this actually more likely points
    to an error in the linter itself. Also checks if THIS / SUPER / invalid method returns are
    used."""
    try:
        _ = ctx.get_var_type(expr.name, strict=False)
    except TypeError as e:
        yield ErrorInfo(message=f"{e}", violating=expr)


@lint_check("VAR001")
def variable_existence_and_capitalization(expr: tf.SimpleVariable, ctx: Context):
    """Validate that variables are capitalized properly (or even exist at all)"""
    var_type = ctx.get_var_type(expr.name, strict=True)

    if var_type is None:
        suggestion = ctx.get_var_suggestion(expr.name)
        msg = f"Variable {expr.name} cannot be found in the current context"
        if suggestion is not None:
            msg += f", did you mean '{suggestion}'?"
        yield ErrorInfo(message=msg, violating=expr)


def _is_camel_case(s: str) -> bool:
    """Check if string s is CamelCase (i.e. contains both casings, starts with a capital letter,
    and contains no underscores)."""
    return s[0].isupper() and s != s.upper() and "_" not in s


def _get_type_prefix(typ: str, ctx: Context, settings: Settings) -> str | None:
    """Get type prefix for variable."""
    if is_array(typ):
        _, base_typ = get_array_dims_and_base_type(typ)
        base_prefix = _get_type_prefix(base_typ, ctx, settings)
        if base_prefix is None:
            return None

        # nested arrays will still only have a single 'a' name prefix
        arr_prefix = settings.array_prefix or ""
        return arr_prefix + base_prefix.lstrip(arr_prefix)

    if is_reference(typ):
        base_typ = get_reference_base_type(typ)
        base_prefix = _get_type_prefix(base_typ, ctx, settings)
        if base_prefix is None:
            return None

        # can REFERENCE TO REFERENCE TO even happen?
        ref_prefix = settings.reference_prefix or ""
        return ref_prefix + base_prefix.lstrip(ref_prefix)

    prefix = settings.type_prefixes.get(typ)
    if prefix is not None:
        return prefix
    for typ_re, prefix in settings.type_prefixes.items():
        if re.match(typ_re, typ):
            return prefix
    if typ in ctx.code.function_blocks and settings.function_block_prefix is not None:
        return settings.function_block_prefix
    if typ in ctx.code.interfaces and settings.interface_prefix is not None:
        return settings.interface_prefix
    if typ in ctx.code.data_types:
        dtyp = ctx.code.data_types.get(typ)
        if isinstance(dtyp.item, tf.EnumeratedTypeDeclaration):
            if settings.enum_prefix is not None:
                return settings.enum_prefix
        elif isinstance(dtyp.item, tf.StructureTypeDeclaration):
            if settings.struct_prefix is not None:
                return settings.struct_prefix
    return None


@lint_check("VAR002")
def declaration_naming_convention(decl: DeclarationSummary, ctx: Context, settings: Settings):
    """Check if variable declarations adhere to our naming standards"""
    var_name = decl.name
    if decl.location is not None:
        # todo: put this in config.yaml
        prefixes = {f"{decl.location.strip('%*')}_"}
    else:
        prefixes = settings.block_prefixes.get(str(decl.block))
        if prefixes is None:
            logger.warning(
                f"Unsupported var block: {decl.block} ({var_name} in {ctx.current_loc})"
            )
            # can't determine var-block based prefix, might as well return now
            return

    type_prefix = _get_type_prefix(decl.type, ctx, settings)
    if type_prefix is None:
        logger.warning(
            f"Unsupported type prefix: {decl.type} ({decl.name} in {ctx.current_loc})"
        )
    else:
        prefixes = {prefix + type_prefix for prefix in prefixes}

    if not any(var_name.startswith(prefix) for prefix in prefixes):
        yield ErrorInfo(
            message=(
                f"Variable {decl.name} of type {decl.type} should start with any of "
                f"{prefixes}, as it is in a {decl.block} block"
            ),
            violating=decl,
        )


@lint_check("VAR100")
def uninitialized_var_read(stat: tf.Statement, ctx: Context):
    """Check whether uninitialized variables are read before they are written."""

    # todo: also check this in function block bodies
    if ctx.current_method is None:
        return

    # the 'candidate' variables which are not initialized
    uninitialized_vars = [
        var
        for var, decl in ctx.current_method.declarations.items()
        if not tc3.decl_is_initialized(decl)
    ]
    if not uninitialized_vars:
        return

    # we want to exclude __QUERY_INTERFACE calls, as they are don't read the variable
    # value, but rather inspect the type of the provided values
    def _exclude_queryinterface(_expr: tf.Expression) -> bool:
        return tc3.is_call_to(_expr, "__QUERYINTERFACE")

    for expr in get_expressions(stat):
        for subexpr in get_subexpressions(expr, exclude=_exclude_queryinterface):
            if not isinstance(subexpr, tf.SimpleVariable):
                continue

            # check if variable may be uninitialized
            var_name = str(subexpr.name)
            if not any(tc3.streq(var_name, v) for v in uninitialized_vars):
                continue

            # the subexpression may be the assignment part of an assignment statement
            # todo: x = x must also be checked
            if is_assignment_for(var_name, stat):
                continue

            if not has_assignment_before(stat, ctx.current_method, var_name):
                yield ErrorInfo(
                    message=f"Variable {var_name} may be read before it is assigned to",
                    violating=subexpr,
                )
