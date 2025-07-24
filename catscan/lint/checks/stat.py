import blark.transform as tf

from catscan.lint.base import lint_check
from catscan.lint.context import Context
from catscan.lint.error import ErrorInfo
from catscan.utils import log, tc3

logger = log.get_logger()


@lint_check("STAT001")
def case_statement_cases(stat: tf.CaseStatement, ctx: Context):
    """Check whether all enum values are present in a case statement (or an else statement must
    be present)"""
    if stat.else_clause is not None:
        return

    expr_type_name = ctx.get_expr_type(stat.expression)
    expr_type_decl = tc3.get_case_insensitive(ctx.code.data_types, expr_type_name)
    if expr_type_decl is None:
        return

    expr_type = expr_type_decl.item
    # we can only really check for enum values
    if not isinstance(expr_type, tf.EnumeratedTypeDeclaration):
        return

    enum_values = {str(value.name) for value in expr_type.init.spec.values}
    for case in stat.cases:
        for match in case.matches:
            if not isinstance(match, tf.EnumeratedValue):
                logger.warning(
                    f"Non-enumerated value in enum case match: {match} ({type(match)})"
                )
                continue

            for val in enum_values:
                # enumerated values are dotted identifiers
                if tc3.streq(match.name, f"{expr_type.name}.{val}"):
                    enum_values.remove(val)
                    break
            else:
                logger.warning(
                    f"Found unknown enumerated value for enum {expr_type.name}: {match}"
                )

    if enum_values:
        yield ErrorInfo(
            message=(
                f"Case statement without else clause is missing cases for enum type "
                f"{expr_type.name} (missing values {enum_values})"
            ),
            violating=stat,
        )
