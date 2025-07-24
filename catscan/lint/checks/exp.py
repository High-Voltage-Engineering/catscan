import blark.transform as tf

from catscan.lint.base import lint_check
from catscan.lint.context import Context
from catscan.lint.error import ErrorInfo
from catscan.utils import tc3


@lint_check("EXP001")
def unsigned_underflow(expr: tf.BinaryOperation, ctx: Context):
    """Detect possible unsigned underflows in the code. This is a common cause for buffer
    overruns when (accidentally) done in for loop bounds."""
    if expr.op != "-":
        return

    if ctx.get_expr_type(expr) in tc3.BUILTIN_UNSIGNED_INTEGERS:
        yield ErrorInfo(
            message="Potential unsigned integer underflow in subtraction expression",
            violating=expr,
        )


@lint_check("EXP002")
def division_by_zero(expr: tf.BinaryOperation):
    """Detect potential divisions by zero in the code."""
    if expr.op != "/":
        return

    if isinstance(expr.right, tf.Constant):
        return

    # SIZEOF always returns a constant
    # the TwinCAT compiler _should_ check these kinds of divisions by zero (right? right?)
    if tc3.is_call_to(expr.right, "SIZEOF"):
        return

    yield ErrorInfo(
        message="Potential division by zero",
        violating=expr,
    )
