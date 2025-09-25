import blark.transform as tf
from blark.summary import FunctionBlockSummary, MethodSummary

from catscan.lint.base import lint_check
from catscan.lint.context import Context
from catscan.lint.error import ErrorInfo
from catscan.settings import Settings
from catscan.utils import tc3
from catscan.utils.program import all_subexpressions
from catscan.utils.tc3 import is_abstract


@lint_check("FUNC001")
def function_exists(stat: tf.FunctionCallStatement, ctx: Context, settings: Settings):
    """Check if all called functions exist, and have the right capitalization."""
    if isinstance(stat.name, tf.SimpleVariable):
        func_name = stat.name.name
        if func_name in settings.builtin_functions:
            return

        try:
            var_type = ctx.get_var_type(func_name, strict=True)
        except TypeError:
            return

        if var_type is None:
            suggestion = (
                func_name.upper()
                if func_name.upper() in settings.builtin_functions
                else ctx.get_var_suggestion(func_name)
            )
            msg = f"Function {func_name} not found"
            if suggestion is not None:
                msg += f", did you mean '{suggestion}'?"

            yield ErrorInfo(message=msg, violating=stat.name)


@lint_check("FUNC100")
def super_call_only_current_method(stat: tf.FunctionCallStatement, ctx: Context):
    """Check if a SUPER^.<method>() call ONLY happens from <method> itself."""
    if ctx.current_method is None:
        return

    if isinstance(stat.name, tf.MultiElementVariable):
        if tc3.is_super(stat.name.name.name):
            unk_access = ErrorInfo(
                message="Unknown access into SUPER^ for method call",
                violating=stat,
            )
            if len(stat.name.elements) > 1:
                yield unk_access
            elt = stat.name.elements[0]
            if not isinstance(elt, tf.FieldSelector):
                yield unk_access

            if not tc3.streq(elt.field.name, ctx.current_method.name):
                yield ErrorInfo(
                    message=(
                        f"Invalid SUPER^ call from {ctx.current_method.name}: "
                        f"{elt.field.name}, you should call the method directly."
                    ),
                    violating=stat,
                )


@lint_check("FUNC101")
def super_call_when_possible(meth: MethodSummary, ctx: Context):
    """Checks that a SUPER^.<method>() call is always present in a method if possible, though
    it may occur on some optional code path."""
    fb = ctx.current_function_block
    fb_super, meth_super = next(
        (
            (ext, mth)
            for ext in ctx.get_all_extends(fb, with_self=False)
            for mth in ext.methods
            if tc3.streq(mth.name, meth.name)
        ),
        (None, None),
    )
    if fb_super is None:
        # no possible SUPER call, so none expected
        return
    if is_abstract(meth_super):
        # abstract super method, so no super call expected
        return

    for subexpr in all_subexpressions(meth):
        if isinstance(subexpr, tf.FunctionCall):
            if isinstance(subexpr.name, tf.MultiElementVariable):
                is_super_call = (
                    tc3.is_super(subexpr.name.name.name)  # SUPER.<something>
                    and len(subexpr.name.elements) == 1
                    and isinstance(subexpr.name.elements[0], tf.FieldSelector)
                    and tc3.streq(subexpr.name.elements[0].field.name, meth.name)
                )
                if is_super_call:
                    break
    else:
        yield ErrorInfo(
            message=(
                f"Missing super call in method {meth.name} of function block {fb.name} "
                f"(first SUPER with method is {fb_super.name})"
            )
        )


@lint_check("FUNC102")
def super_call_in_function_block(fb: FunctionBlockSummary, ctx: Context):
    """Check whether SUPER^() is called from a function block body (with extensions)"""

    # expect super call if function block is non-abstract and has some non-abstract parent fb
    expect_super_call = not tc3.is_abstract(fb) and fb.implementation is not None
    if not expect_super_call:
        return
    non_abstract_super = next(
        (ext for ext in ctx.get_all_extends(fb, with_self=False) if not tc3.is_abstract(ext)),
        None,
    )
    if non_abstract_super is None:
        return

    for subexpr in all_subexpressions(fb.implementation):
        if isinstance(subexpr, tf.FunctionCall):
            if isinstance(subexpr.name, tf.SimpleVariable):
                is_super_call = tc3.is_super(subexpr.name.name)
                if is_super_call:
                    break
    else:
        yield ErrorInfo(
            message=(
                f"Missing super call in function block {fb.name} body (is non-abstract and "
                f"extends non-abstract function block {non_abstract_super.name})"
            )
        )
