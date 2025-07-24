import inspect
import re
from collections import defaultdict
from collections.abc import Callable, Iterator
from typing import Annotated, TypedDict, Unpack

import blark.transform as tf
from blark.summary import (
    CodeSummary,
    Summary,
)
from pydantic import BaseModel, StringConstraints

from catscan.settings import CheckLevel, Settings
from catscan.utils import log
from catscan.utils.program import (
    get_expressions,
    get_statements,
    get_subexpressions,
)
from .context import Context
from .error import Error, ErrorInfo

logger = log.get_logger()

CheckableObject = tf.Statement | Summary | tf.Expression
LintCheckFunction = Callable[[CheckableObject, ...], Iterator[ErrorInfo]]
__REGISTERED_CODES__: set[str] = set()
__REGISTERED_CHECKS__: dict[type[CheckableObject], list["LintCheck"]] = defaultdict(list)

CODE_PATT = r"[A-Z]{2,4}\d{3,4}"
LintCode = Annotated[str, StringConstraints(pattern=CODE_PATT)]
NOQA_RE = re.compile(fr"//\s*noqa:\s*({CODE_PATT}(\s+{CODE_PATT})*)$")


class ExtraCheckParams(TypedDict):
    ctx: Context
    settings: Settings


def _is_noqa(error_line: str, code: str) -> bool:
    noqa = NOQA_RE.search(error_line)
    if noqa is None:
        return False
    return code in noqa.string


class LintCheck(BaseModel):
    """Wrapped lint check with additional meta info"""

    func: LintCheckFunction
    code: LintCode

    @property
    def name(self) -> str:
        return self.func.__name__

    @property
    def doc(self) -> str:
        return re.sub(r"[\n\s]+", " ", self.func.__doc__)

    def __call__(
        self,
        obj: CheckableObject,
        **kwargs: Unpack[ExtraCheckParams],
    ) -> Iterator[Error]:
        """Wrapped call to actual lint check function"""
        _kwargs = ExtraCheckParams(**kwargs)
        _settings: Settings = _kwargs["settings"]
        _err_settings = _settings.checks.get(self.code)
        _do_yield = _err_settings is None or (
            _err_settings.enabled and _err_settings.level == CheckLevel.ERROR
        )

        # check if this check is skipped
        check_settings = _settings.checks.get(self.code)
        check_level = CheckLevel.ERROR
        if check_settings is not None:
            if not check_settings.enabled:
                # disabled in settings
                return
            check_level = check_settings.level

        if check_level > _settings.level:
            # disabled by level
            return

        # inject context / settings kwargs
        sig = inspect.signature(self.func)
        params = set(sig.parameters)
        kwargs = {k: v for k, v in _kwargs.items() if k in params}

        if missing := set(kwargs) - params:
            msg = f"Missing kwargs for lint check {self.code}: {missing}"
            raise ValueError(msg)

        for info in self.func(obj, **kwargs):
            info.ctx = _kwargs["ctx"]
            err = Error.from_info(self.code, info)

            # check if error was ignored for this line (only possible if violating line can
            # be found
            error_line = err.loc.error_line()
            if error_line is None or not _is_noqa(error_line, self.code):
                err.pretty_print(f"{check_level.name}:")
                if _do_yield:
                    yield err


def lint_check(code: str) -> Callable[[LintCheckFunction], LintCheck]:
    """Decorator for a linting check with a certain code (similar to python linting style codes,
    ARG001, S101, etc. The function being wrapped must take a single summary parameter, and
    return a message and optionally a meta object."""
    if not re.fullmatch(CODE_PATT, code):
        msg = f"'{code}' is not a valid value for a catscan lint check"
        raise ValueError(msg)

    if code in __REGISTERED_CODES__:
        msg = f"Code '{code}' is already used for a linter check"
        raise RuntimeError(msg)
    __REGISTERED_CODES__.add(code)

    def decorator(func: LintCheckFunction) -> LintCheck:
        wrapped = LintCheck(func=func, code=code)

        sig = inspect.signature(func)
        check_type = next(iter(sig.parameters.values())).annotation
        assert issubclass(
            check_type, CheckableObject
        ), "Lint check must act on summaries, statements or expressions"
        __REGISTERED_CHECKS__[check_type].append(wrapped)  # type: ignore

        return wrapped

    return decorator


def list_() -> Iterator[LintCheck]:
    """List all registered lint checks (across all types)"""
    for _, checks in __REGISTERED_CHECKS__.items():
        yield from checks


def lint(code: CodeSummary, settings: Settings):
    ctx = Context(code=code, settings=settings)
    errors = []

    # some objects may have already been checked, as they qualify both as an expression and
    # as a statement (like FunctionCallStatements)
    already_checked = set()

    def _do_checks(obj: CheckableObject):
        """Execute all checks registered for this object"""
        if id(obj) in already_checked:
            return

        for typ, checks in __REGISTERED_CHECKS__.items():
            if isinstance(obj, typ):
                for check in checks:
                    errors.extend(check(obj, ctx=ctx, settings=settings))
        already_checked.add(id(obj))

    for fb in code.function_blocks.values():
        with ctx.function_block(fb):
            _do_checks(fb)

            for decl in fb.declarations.values():
                _do_checks(decl)
            if fb.implementation is not None:
                for stat in get_statements(fb.implementation):
                    _do_checks(stat)
                    for expr in get_expressions(stat):
                        for subexpr in get_subexpressions(expr):
                            _do_checks(subexpr)

            for method in fb.methods:
                with ctx.method(method):
                    _do_checks(method)
                    for decl in method.declarations.values():
                        _do_checks(decl)
                    for stat in get_statements(method):
                        _do_checks(stat)
                        for expr in get_expressions(stat):
                            for subexpr in get_subexpressions(expr):
                                _do_checks(subexpr)

            for prop in fb.properties:
                _do_checks(prop)
                with ctx.method(prop.getter):
                    for decl in prop.getter.declarations.values():
                        _do_checks(decl)
                    for stat in get_statements(prop.getter):
                        _do_checks(stat)
                        for expr in get_expressions(stat):
                            for subexpr in get_subexpressions(expr):
                                _do_checks(subexpr)
                with ctx.method(prop.setter):
                    for decl in prop.setter.declarations.values():
                        _do_checks(decl)
                    for stat in get_statements(prop.setter):
                        _do_checks(stat)
                        for expr in get_expressions(stat):
                            for subexpr in get_subexpressions(expr):
                                _do_checks(subexpr)

    if errors:
        logger.error(f"{len(errors)} errors found")
        return 1
    return 0
