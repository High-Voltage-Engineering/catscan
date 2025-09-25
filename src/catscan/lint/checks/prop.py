import blark.transform as tf
from blark.summary import PropertySummary

from catscan.lint.base import lint_check
from catscan.lint.error import ErrorInfo
from catscan.utils import tc3
from catscan.utils.program import (
    all_subexpressions,
    get_statements,
    is_assignment_for,
)


@lint_check("PROP001")
def prop_setter_reads_set_value(prop: PropertySummary):
    """Check whether the property setter value is actually read."""
    if prop.setter.implementation:
        for subexpr in all_subexpressions(prop.setter):
            is_prop_setter_read = isinstance(subexpr, tf.SimpleVariable) and tc3.streq(
                subexpr.name, prop.name
            )
            if is_prop_setter_read:
                return

        yield ErrorInfo(message=f"Property setter variable '{prop.name}' is never read")


@lint_check("PROP002")
def prop_setter_value_not_written_to(prop: PropertySummary):
    """Check whether the property setter value is never written to."""
    if prop.setter.implementation:
        for stat in get_statements(prop.setter):
            if is_assignment_for(prop.name, stat, adr_is_assignment=False):
                yield ErrorInfo(
                    message=f"Property setter variable '{prop.name}' is written to",
                    violating=stat,
                )
