from blark.summary import MethodSummary, PropertySummary

from catscan.lint.base import lint_check
from catscan.lint.context import Context
from catscan.lint.error import ErrorInfo
from catscan.utils import tc3
from catscan.utils.program import (
    has_assignment,
)
from catscan.utils.tc3 import is_abstract


@lint_check("RET001")
def method_has_return(method: MethodSummary, ctx: Context):
    """Check if method has return statement (assignment to method name)"""
    if tc3.is_abstract(method):
        return
    if method.implementation and method.return_type:
        if not has_assignment(method, str(method.name)):
            msg = (
                f"Method {ctx.current_function_block.name}.{method.name} does not return a "
                f"value on all code paths, even though it should "
                f"(return type {method.return_type})"
            )
            yield ErrorInfo(message=msg)


@lint_check("RET002")
def method_returns_all_out_vars(method: MethodSummary, ctx: Context):
    """Check if method assigns to all output variables"""
    if is_abstract(method):
        return

    if method.implementation:
        for decl in method.declarations.values():
            if decl.block.upper() == "VAR_OUTPUT":
                if tc3.decl_is_initialized(decl):
                    # out var is initialized on definition
                    continue

                if not has_assignment(method, str(decl.name)):
                    msg = (
                        f"Method {ctx.current_function_block.name}.{method.name} does not "
                        f"assign to output variable {decl.name} on all code paths"
                    )
                    yield ErrorInfo(message=msg)


@lint_check("RET101")
def property_has_return(prop: PropertySummary):
    """Check if property getter has return statement (assignment to property name)"""
    getter = prop.getter
    if getter.implementation and getter.item.return_type:
        if not has_assignment(getter, str(prop.name)):
            msg = (
                f"Property getter {getter.name} does not return a value on all code paths, "
                f"even though it should (property type {getter.item.return_type})"
            )
            yield ErrorInfo(message=msg)

# todo: this must check nested function calls...
# @lint_check("RET202")
# def function_block_returns_all_out_vars(fb: FunctionBlockSummary, ctx: Context):
#     if (fb.item.access or 0) & tf.AccessSpecifier.abstract.value:
#         return
#
#     if fb.implementation:
#         for decl in fb.declarations.values():
#             if decl.block.upper() == "VAR_OUTPUT":
#                 if tc3.decl_is_initialized(decl):
#                      # out var is initialized on definition
#                     continue
#
#                 if not has_assignment(fb.implementation, str(decl.name)):
#                     msg = (
#                         f"Function block {ctx.current_function_block.name} does not "
#                         f"assign to output variable {decl.name} on all code paths"
#                     )
#                     yield ErrorInfo(message=msg)
