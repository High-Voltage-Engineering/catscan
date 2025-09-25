import blark.transform as tf
from blark.summary import DeclarationSummary, MethodSummary

from catscan.lint.base import lint_check
from catscan.lint.error import ErrorInfo
from catscan.utils import tc3
from catscan.utils.tc3 import is_super_call


@lint_check("METH001")
def method_not_only_super(meth: MethodSummary):
    """Checks whether a method is not just a single super call"""
    if meth.implementation and len(meth.implementation.statements) == 1:
        stat = meth.implementation.statements[0]
        if is_super_call(stat, meth.name):
            stat: tf.FunctionCall

            # todo: check output params too, currently, it will find the calls unequal
            meth_inp_args = tc3.get_case_insensitive(
                meth.declarations_by_block,
                "VAR_INPUT",
                {},
            )

            if len(stat.parameters) == 0:
                yield ErrorInfo(
                    message=(
                        "Method consists of only SUPER^ call, consider removing virtual call"
                    ),
                    violating=stat,
                )
            elif len(meth_inp_args) == len(stat.parameters):

                def _is_passthrough_arg(
                    param: tf.InputParameterAssignment,
                    arg: DeclarationSummary,
                ) -> bool:
                    return isinstance(param.value, tf.SimpleVariable) and tc3.streq(
                        param.value.name, arg.name
                    )

                is_direct_call = True
                if any(param.name for param in stat.parameters):
                    # named parameters used
                    stat_params = {str(param.name): param for param in stat.parameters}
                    if {str(arg.name) for arg in meth_inp_args.values()} != set(stat_params):
                        is_direct_call = False
                    else:
                        for arg in meth_inp_args.values():
                            if not _is_passthrough_arg(stat_params[str(arg.name)], arg):
                                is_direct_call = False
                                break
                else:
                    # unnamed parameters
                    zipped = zip(meth_inp_args.values(), stat.parameters, strict=False)
                    for meth_arg, param in zipped:
                        if not _is_passthrough_arg(param, meth_arg):
                            is_direct_call = False
                            break

                if is_direct_call:
                    yield ErrorInfo(
                        message=(
                            "Method consists of only SUPER^ call with passed through "
                            "parameters, consider removing virtual call"
                        ),
                        violating=stat,
                    )
