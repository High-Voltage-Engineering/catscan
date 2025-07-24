from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TypeVar

import blark.transform as tf
from blark.summary import (
    CodeSummary,
    DeclarationSummary,
    FunctionBlockSummary,
    MethodSummary,
    PropertyGetSetSummary,
)

from catscan.settings import Settings
from catscan.utils import log, tc3
from catscan.utils.tc3 import (
    get_array_dims_and_base_type,
    get_case_insensitive,
    get_case_insensitive_with_fixed_key,
    streq,
)

logger = log.get_logger()

_T = TypeVar("_T")

ComplexType = object()


def _push_stack_context(stack: list[_T], item: _T):
    stack.append(item)
    yield
    stack.pop()


@dataclass
class Context:
    code: CodeSummary
    settings: Settings
    var_stack: list[dict[str, DeclarationSummary]] = field(default_factory=list)

    _current_fb: FunctionBlockSummary | None = None
    _current_method: MethodSummary | PropertyGetSetSummary | None = None

    def __post_init__(self):
        # collect all globals and add them to the variable stack
        _globals = {}
        for decl in self.code.globals.values():
            _globals.update(decl.declarations)
        self.var_stack.append(_globals)

    def __str__(self):
        loc = self._current_fb.name
        if self._current_method is not None:
            loc += f"/{self._current_method.name}"

        reduced_stack = [
            {name: decl.type for name, decl in layer.items()} for layer in self.var_stack
        ]
        fb_decls = (
            self._get_fb_decl_types(self._current_fb) if self._current_fb is not None else None
        )
        return f"Ctx<{loc}\n {fb_decls}\n {reduced_stack}\n>"

    @property
    def current_loc(self) -> str:
        """Get pretty name for current context location"""
        if self.current_function_block is None:
            # todo: current file ctx?
            return "<global>"
        ctx = self._current_fb.name
        if self._current_method is not None:
            ctx += f".{self.current_method.name}"
        return ctx

    def get_field_type(self, base_typ: str, field: str) -> str | None:
        if base_typ in self.code.function_blocks:
            base_fb = self.code.function_blocks[base_typ]
            squashed_fb = base_fb.squash_base_extends(self.code.function_blocks)
            _field = squashed_fb.declarations.get(field)
            if _field is None:
                for prop in squashed_fb.properties:
                    if streq(prop.name, field):
                        # todo: this is actually a more complex structure
                        return str(prop.getter.item.return_type)
                return None
            return _field.type
        elif base_typ in self.code.data_types:
            base_dt = self.code.data_types[base_typ]
            squashed_dt = base_dt.squash_base_extends(self.code.data_types)
            _field = squashed_dt.declarations.get(field)
            if _field is None:
                return None
            return _field.type
        return None

    def _get_var_type(
        self,
        var: str,
        strict: bool = False,
    ) -> tuple[str | None, str | type(ComplexType) | None]:
        """Get the type of a given variable as a string. The variable must not be of a
        function-type. I guess this is fine, I haven't really seen second-order functions
        being used anywhere. Function objects are also not parsed as being a sub expression
        with get_subexpressions. Returns the variable type as well as the fixed variable name
        (which will always just be the input var argument if strict mode is enabled."""

        def _dict_getter(d: dict[str, _T], k: str) -> tuple[str | None, _T | None]:
            if strict:
                return k, d.get(k)
            else:
                return get_case_insensitive_with_fixed_key(d, str(k))

        def _streq(s1: str, s2: str) -> bool:
            return str(s1) == str(s2) if strict else streq(s1, s2)

        # first check THIS and other builtins (TRUE, FALSE, etc.)
        for this in ("THIS", "THIS^"):
            if _streq(str(var), this):
                if self._current_fb is None:
                    msg = "THIS used outside of function block"
                    raise TypeError(msg)
                return this, self._current_fb.name
        for supr in ("SUPER", "SUPER^"):
            if _streq(str(var), supr):
                if self._current_fb is None:
                    msg = "SUPER used outside of function block"
                    raise TypeError(msg)

                if self._current_method is None:
                    # must be in function block body, so I guess just take the first extension?
                    # not sure how multiple inheritance works here
                    return supr, str(self._current_fb.extends[0])

                # find correct extension by checking the methods that are implemented for this
                # extension
                for ext in self._current_fb.extends:
                    _, ext_fb = _dict_getter(self.code.function_blocks, ext)
                    if ext_fb is not None:
                        # todo: actually, squashing is not entirely correct, as the type of
                        # SUPER^ would be that of the first function block with the
                        # implementation in the inheritance structure (I think), while this may
                        # find some intermediate function block type
                        squashed_ext_fb = ext_fb.squash_base_extends(self.code.function_blocks)
                        meth = next(
                            (
                                meth
                                for meth in squashed_ext_fb.methods + squashed_ext_fb.properties
                                if _streq(meth.name, self._current_method.name)
                            ),
                            None,
                        )
                        if meth is not None:
                            return supr, str(ext)
                # proper extension not found
                logger.warning(f"Failed to find type of SUPER in {self.current_loc}")
                return supr, None

        # builtin symbols may have some type as well
        k, typ = _dict_getter(self.settings.builtin_symbols, var)
        if typ is not None:
            return k, typ

        # check if variable is a type or a function (in which case we return some placeholder)
        complex_types = [
            self.code.data_types,
            self.code.function_blocks,
            tc3.BUILTIN_TYPE_CONVERSIONS,
            tc3.BUILTIN_FUNCTIONS,
            self.code.functions,
        ]
        for _complex_types in complex_types:
            # obj is now not a type, but some data type object, function block object, etc.
            k, obj = _dict_getter(_complex_types, var)
            if obj is not None:
                return k, ComplexType

        # todo: I am unsure if scoping in TwinCAT works in this order, but it's probably fine
        #       it would be pretty bad if shadowing occurs anyway...
        if self._current_fb is not None:
            fb_vars = self._get_fb_decl_types(self._current_fb)
            k, typ = _dict_getter(fb_vars, var)
            if typ is not None:
                return k, typ
        if self._current_method is not None and _streq(self._current_method.name, var):
            if isinstance(self._current_method, MethodSummary):
                if self._current_method.return_type is None:
                    msg = f"Method {self._current_method.name!s} has no return type"
                    raise TypeError(msg)
                return self._current_method.name, self._current_method.return_type
            else:
                return self._current_method.name, self._current_method.item.return_type

        for layer in reversed(self.var_stack):
            k, decl = _dict_getter(layer, var)
            if decl is not None:
                return k, decl.type

        return None, None

    def get_var_type(self, var: str, strict: bool = False) -> str | type(ComplexType) | None:
        """Get variable type from current context (name may not be strictly equal if
        strict == False)"""
        return self._get_var_type(var, strict=strict)[1]

    def get_var_suggestion(self, var: str) -> str | None:
        """Try to suggest a close variable name for a variable that may not exist or be
        capitalized in the wrong way."""
        return self._get_var_type(var, strict=False)[0]

    def get_multi_element_type(
        self, name: str, elements: list[tf.SubscriptList | tf.FieldSelector]
    ) -> str | None:
        """Get the type of a multi element variable"""
        typ = self.get_var_type(name)
        for elt in elements:
            if not isinstance(typ, str):
                return typ

            if isinstance(elt, tf.SubscriptList):
                # may be multi-dereference
                dims, typ = get_array_dims_and_base_type(typ)
                if dims != len(elt.subscripts):
                    logger.warning(
                        f"Unsupported: partial multi-dimensional array access "
                        f"(in {self.current_loc})"
                    )
                    return None
            else:
                assert isinstance(elt, tf.FieldSelector)
                typ = self.get_field_type(typ, str(elt.field.name))
        return typ

    def get_expr_type(self, expr: tf.Expression) -> str | None:
        """Try to determine the type of a (transformed) blark expression."""

        # supported by tf.Integer, Real, BitString,
        if type_name := getattr(expr, "type_name", None):
            return type_name

        default_arithmetic_types = {
            tf.Integer: "INT",
            tf.Real: "LREAL",
            tf.Boolean: "BOOLEAN",
            tf.Duration: "TIME",
            tf.Lduration: "LTIME",
            tf.TimeOfDay: "TIME_OF_DAY",
            tf.LtimeOfDay: "LTIME_OF_DAY",
            tf.Date: "DATE",
            tf.Ldate: "LDATE",
            tf.DateTime: "DATE_AND_TIME",
            tf.LdateTime: "LDATE_AND_TIME",
            tf.String: "STRING",
            # tf.BitString:  None,  # todo: what is the default here?
        }

        for expr_typ, default in default_arithmetic_types.items():
            if isinstance(expr, expr_typ):
                return default
        if isinstance(expr, tf.DirectVariable):
            raise NotImplementedError
        elif isinstance(expr, tf.SimpleVariable):
            return self.get_var_type(str(expr.name))
        elif isinstance(expr, tf.MultiElementVariable):
            return self.get_multi_element_type(str(expr.name), expr.elements)
        elif isinstance(expr, tf.UnaryOperation):
            match str(expr.op):
                case "NOT":
                    return "BOOLEAN"
                case "-" | "+":
                    return self.get_expr_type(expr.expr)
                case _:
                    raise NotImplementedError
        elif isinstance(expr, tf.BinaryOperation):
            match str(expr.op):
                case (
                "OR"
                | "XOR"
                | "AND"
                | "AND_THEN"
                | "OR_ELSE"
                | "="
                | "<>"
                | "<="
                | ">="
                | "<"
                | ">"
                ):
                    return "BOOLEAN"
                case "MOD":
                    return self.get_expr_type(expr.left)
                case "+" | "-" | "*" | "/":
                    ltyp = self.get_expr_type(expr.left)
                    rtyp = self.get_expr_type(expr.right)
                    return tc3.common_arithmetic_type(ltyp, rtyp)
                case _:
                    raise NotImplementedError
        elif isinstance(expr, tf.ParenthesizedExpression | tf.BracketedExpression):
            # NOTE: bracketed expression is EXCLUSIVELY used for string length specifications
            return self.get_expr_type(expr.expr)
        elif isinstance(expr, tf.FunctionCall):
            funcname = str(expr.name.name)
            if conv_to := get_case_insensitive(tc3.BUILTIN_TYPE_CONVERSIONS, funcname):
                return conv_to
            if builtin_ret := get_case_insensitive(tc3.BUILTIN_FUNCTIONS, funcname):
                return builtin_ret
            if func := get_case_insensitive(self.code.functions, funcname):
                return func.return_type
            if isinstance(fb := self.get_var_type(funcname), str):
                # function block call
                return fb
        logger.warning(f"Unsupported or unknown expression type accessor: {expr}")
        return None

    def get_all_extends(
        self,
        fb: FunctionBlockSummary,
        with_self: bool = True,
    ) -> Iterator[FunctionBlockSummary]:
        """Get entire inheritance structure of function block"""
        if with_self:
            yield fb
        for ext in fb.extends or []:
            ext_fb = tc3.get_case_insensitive(self.code.function_blocks, ext)
            if ext_fb is not None:
                # always include self in this case, as it should return the entire structure
                yield from self.get_all_extends(ext_fb, with_self=True)
            else:
                logger.warning(f"Failed to get function block extension '{ext}' for {fb.name}")

    def _get_fb_decl_types(
        self, fb: FunctionBlockSummary
    ) -> dict[str, str | type(ComplexType)]:
        """Get field names for a function block definition (including inherited fields)"""
        squashed = fb.squash_base_extends(self.code.function_blocks)
        decls = {str(name): decl.type for name, decl in squashed.declarations.items()}
        props = {
            str(prop.name): prop.getter.item.return_type.full_type_name
            for prop in squashed.properties
        }
        methods = {str(method.name): ComplexType for method in squashed.methods}
        return decls | props | methods

    @property
    def current_function_block(self) -> FunctionBlockSummary | None:
        return self._current_fb

    @contextmanager
    def function_block(self, fb: FunctionBlockSummary):
        assert self._current_fb is None
        self._current_fb = fb
        yield
        # todo: unify this? it is annoying to deal with properties and declarations in the same
        #       way. Perhaps we can extract some type info from both
        # yield from _push_stack_context(self.var_stack, self._get_fb_declarations(fb))
        self._current_fb = None

    @property
    def current_method(self) -> MethodSummary | PropertyGetSetSummary | None:
        return self._current_method

    @contextmanager
    def method(self, method: MethodSummary | PropertyGetSetSummary):
        assert self._current_method is None
        self._current_method = method
        yield from _push_stack_context(self.var_stack, method.declarations)
        self._current_method = None
