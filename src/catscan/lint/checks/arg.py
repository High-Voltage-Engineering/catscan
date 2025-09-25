import blark.transform as tf

from catscan.lint.base import lint_check
from catscan.lint.context import Context
from catscan.lint.error import ErrorInfo
from catscan.settings import Settings


@lint_check("ARG001")
def function_call_named_args(stat: tf.FunctionCallStatement, ctx: Context, settings: Settings):
    """Checks whether a function call with at least a configured amount of parameters uses named
    arguments, as to prevent mistakes in (compatible) argument order."""
    if len(stat.parameters) <= settings.max_nameless_args:
        return
    if str(stat.name) in settings.nameless_arg_functions:
        return

    meth_info: str | None = None
    if isinstance(stat.name, tf.MultiElementVariable):
        *child, meth_name = stat.name.elements
        base_typ = None

        # the last accessor may be an array selector, which may happen if we have an array of
        # function blocks of which we call the body through direct array access
        # note that we may still be calling a function block body if it is a field which we
        # access and call, but in this case it may be excluded globally
        if isinstance(meth_name, tf.FieldSelector):
            meth_name = meth_name.field.name
            base_typ = ctx.get_multi_element_type(str(stat.name.name), list(child))
        else:
            # no explicit method name
            meth_name = None
    else:
        assert isinstance(stat.name, tf.SimpleVariable)
        meth_name = stat.name.name
        base_typ = None
        if ctx.current_function_block is not None:
            base_typ = ctx.current_function_block.name

    # the base type may not be detected if:
    # - it is a field of a built-in TwinCAT type
    # - it is a partial multi-dimensional array access
    #
    # We allow nameless arguments in methods if:
    # - the (type, method) pair is specifically excluded (this is the nicest way of
    #   excluding methods)
    # - the dotted expression is specifically excluded (this is not very nice, as it
    #   depends on the field name, not the type name, which may vary between usages)
    # - the method name is excluded (this is pretty broad, and you may exclude methods
    #   of other function blocks with the same name accidentally)
    if base_typ is not None:
        meth_info = f"{base_typ}:{meth_name}"
        # todo: check for inheritance
        if (base_typ, meth_name) in settings.nameless_arg_methods:
            return
    if str(stat.name) in settings.nameless_arg_methods:
        return
    if meth_name in settings.nameless_arg_methods:
        return

    for param in stat.parameters:
        if isinstance(param, tf.InputParameterAssignment) and param.name is None:
            msg = f"Unnamed parameter in function call to {stat.name}"
            if meth_info is not None:
                msg += f" (function block method {meth_info})"
            yield ErrorInfo(message=msg, violating=param)
