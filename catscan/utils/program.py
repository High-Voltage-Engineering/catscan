import dataclasses
import html
from collections.abc import Callable, Iterator
from functools import partial

import blark.transform as tf
from blark.summary import (
    MethodSummary,
    PropertyGetSetSummary,
)

from .tc3 import streq

_Graphable = MethodSummary | PropertyGetSetSummary | tf.StatementList


@dataclasses.dataclass
class ProgramNode:
    label: str | None = None

    # the high-level statement to which this node belongs (so an if statement, a loop, etc.)
    stat: tf.Statement | None = None
    prev: set["ProgramNode"] = dataclasses.field(default_factory=set)
    next: set["ProgramNode"] = dataclasses.field(default_factory=set)
    statements: list[tf.Statement] = dataclasses.field(default_factory=list)

    def __hash__(self):
        return hash(id(self))

    def add_next(self, node: "ProgramNode | None" = None, **kwargs):
        if node is None:
            node = ProgramNode(**kwargs)
        self.next.add(node)
        node.prev.add(self)
        return node

    def add_prev(self, node: "ProgramNode | None" = None, **kwargs):
        if node is None:
            node = ProgramNode(**kwargs)
        self.prev.add(node)
        node.next.add(self)
        return node


def get_program_graph(
    obj: _Graphable,
) -> ProgramNode:
    assert obj is not None
    return _get_program_graph(obj)[0]


def _get_program_graph(
    obj: _Graphable | tf.Statement | None,
    start: ProgramNode | None = None,
    end: ProgramNode | None = None,
    exit_destination: ProgramNode | None = None,
    continue_destination: ProgramNode | None = None,
) -> tuple[ProgramNode, ProgramNode | None]:
    """Make a program graph for this object, returning the first and the last node of the
    program. Returns the first and the last node of the program. If code is unreachable,
    then end is None but start is not None.

    The created graph may actually not be connected (that is, there may not be a path from the
    returned start to the returned end, for example in case all code paths in a switch or an
    if/else chain return or exit)."""

    if obj is None:
        return start, end
    if end is None:
        if start is None:
            # we may want to analyze only part of a method, in which case we want to create
            # a start and end node for this statement
            assert start is None and end is None
            end = start = ProgramNode()
        else:
            # (<Node>, None), so this code is unreachable
            return start, end

    if isinstance(obj, MethodSummary | PropertyGetSetSummary):
        # it makes no sense to start a program graph for a method with an existing source node
        assert start is end and not start.statements
        assert continue_destination is None and exit_destination is None
        start.label = f"method {obj.name}"
        impl = obj.implementation
        if impl is not None and impl.statements is not None:
            for stat in impl.statements:
                # progressively append to the head
                _, end = _get_program_graph(stat, start=start, end=end)
                if end is None:
                    # i.e. unreachable code
                    break

        # if no statements occur in the program, just return an empty program
        return start, end
    elif isinstance(obj, tf.StatementList):
        for stat in obj.statements:
            # progressively append to the head
            _, end = _get_program_graph(
                stat,
                start=start,
                end=end,
                continue_destination=continue_destination,
                exit_destination=exit_destination,
            )
        return start, end
    else:
        # a more explicit check about the statements we expect is in the final 'else' clause
        # of course, this may be a bit excessive, but it just ensures that there is no mismatch
        # between blark statements and the things we know of
        assert isinstance(obj, tf.Statement), f"Expected statement, got {type(obj)} ({obj})"
        if isinstance(obj, tf.IfStatement):
            if_end = ProgramNode(label="if_end")
            _, _end = _get_program_graph(
                obj.statements,
                start=start,
                end=end.add_next(stat=obj, label=f"if {obj.if_expression}"),
                continue_destination=continue_destination,
                exit_destination=exit_destination,
            )
            if _end is not None:
                _end.add_next(if_end)

            for elsif in obj.else_ifs:
                _, _end = _get_program_graph(
                    elsif.statements,
                    start=start,
                    end=end.add_next(label=f"elsif {elsif.if_expression}"),
                    continue_destination=continue_destination,
                    exit_destination=exit_destination,
                )
                if _end is not None:
                    _end.add_next(if_end)

            if obj.else_clause is not None:
                _, _end = _get_program_graph(
                    obj.else_clause.statements,
                    start=start,
                    end=end.add_next(label="else"),
                    continue_destination=continue_destination,
                    exit_destination=exit_destination,
                )
                if _end is not None:
                    _end.add_next(if_end)
            else:
                # no else clause means an implicit empty else clause
                end.add_next(label="_else").add_next(if_end)
                pass
            return start, if_end
        elif isinstance(obj, tf.CaseStatement):
            case_node = end.add_next(stat=obj, label=f"CASE {obj.expression}")
            case_end = ProgramNode(label="case_end")

            for case in obj.cases:
                _, _end = _get_program_graph(
                    case.statements,
                    start=start,
                    end=case_node.add_next(stat=obj, label=str(case.matches)),
                    continue_destination=continue_destination,
                    exit_destination=exit_destination,
                )
                if _end is not None:
                    _end.add_next(case_end)
            if obj.else_clause is not None:
                _, _end = _get_program_graph(
                    obj.else_clause.statements,
                    start=start,
                    end=case_node.add_next(label="else"),
                    continue_destination=continue_destination,
                    exit_destination=exit_destination,
                )
                if _end is not None:
                    _end.add_next(case_end)

            # if all cases end in a return statement, the constructed graph will just be
            # disconnected, which is okay, as outside of the function we only use 'start'
            # anyway
            return start, case_end
        elif isinstance(obj, tf.WhileStatement | tf.RepeatStatement | tf.ForStatement):
            loop = end.add_next(stat=obj, label="loop")
            loop_start = loop.add_next(label="loop_start")
            loop_end = ProgramNode(label="loop_end")

            _, _end = _get_program_graph(
                obj.statements,
                start=start,
                end=loop_start,
                continue_destination=loop_start,
                exit_destination=loop_end,
            )
            if _end is not None:
                _end.add_next(loop_end)

            # condition false, add empty node
            loop.add_next(label="_else").add_next(loop_end)
            return start, loop_end
        elif isinstance(obj, tf.LabeledStatement):
            end = end.add_next(stat=obj, label=str(obj.label))
            if obj.statement is not None:
                end.statements.append(obj.statement)
            return start, end
        elif isinstance(obj, tf.ExitStatement):
            if exit_destination is None:
                msg = "EXIT used outside of loop"
                raise ValueError(msg)
            end.statements.append(obj)
            end.add_next(exit_destination)
            return start, None  # unreachable code after
        elif isinstance(obj, tf.ContinueStatement):
            if continue_destination is None:
                msg = "CONTINUE used outside of loop"
                raise ValueError(msg)
            end.statements.append(obj)
            end.add_next(continue_destination)
            return start, None  # unreachable code after
        elif isinstance(obj, tf.ReturnStatement):
            end.statements.append(obj)
            return start, None  # unreachable code after
        elif isinstance(obj, tf.JumpStatement):
            raise NotImplementedError
        else:
            leaf_stat = (
                tf.ChainedFunctionCallStatement
                | tf.NoOpStatement
                | tf.SetStatement
                | tf.ReferenceAssignmentStatement
                | tf.ResetStatement
                | tf.AssignmentStatement
                | tf.FunctionCallStatement
            )
            assert isinstance(obj, leaf_stat)
            end.statements.append(obj)
            return start, end


def program_to_dot(start_node: ProgramNode | _Graphable) -> str:
    """Debug utility for converting a program graph to dot notation."""
    if not isinstance(start_node, ProgramNode):
        start_node = get_program_graph(start_node)

    dot = ["digraph G {"]
    dot.append('    node [fontname = "courier new"];')
    line_break = '<BR  ALIGN="LEFT"/>'
    node_ids = {}
    visited = set()

    def get_node_id(node):
        if node not in node_ids:
            node_ids[node] = f"n{len(node_ids)}"
        return node_ids[node]

    def visit(node):
        if node in visited:
            return
        visited.add(node)

        node_id = get_node_id(node)
        label = line_break.join(html.escape(str(stmt)) for stmt in node.statements)
        if node.label is not None:
            label = f"<B>{html.escape(node.label)}</B>{line_break}{line_break}" + label

        # add extra line break to align last line to the left as well
        dot.append(f"    {node_id} [label=<{label}{line_break}>];")

        for child in node.next:
            child_id = get_node_id(child)
            dot.append(f"    {node_id} -> {child_id};")
            visit(child)

    visit(start_node)
    dot.append("}")
    return "\n".join(dot)


def _find_statement_node(
    graph: ProgramNode,
    target: tf.Statement,
) -> ProgramNode | None:
    """Find a statement node in the graph."""
    todo: set[ProgramNode] = {graph}
    visited: set[ProgramNode] = set()

    while todo:
        node = todo.pop()
        visited.add(node)
        if node.stat is target:
            return node
        for stat in node.statements:
            if stat is target:
                return node

        for nxt in node.next:
            if nxt not in visited:
                todo.add(nxt)

    # target node not found, may be unreachable
    return None


def _predicate_on_all_code_paths(
    source: MethodSummary | PropertyGetSetSummary | tf.StatementList,
    pred: Callable[[tf.Statement], bool],
) -> list[ProgramNode] | None:
    """Check whether a predicate holds on all code paths (for example, whether a return
    statement exists on all paths, or an output variable is assigned on all code paths).
    Returns the failing code path (or None if there is no path that fails)."""
    graph = get_program_graph(source)
    todo: dict[ProgramNode, list[ProgramNode]] = {graph: []}
    visited: set[ProgramNode] = set()

    while todo:
        node, path = todo.popitem()
        visited.add(node)
        if node.stat is not None and pred(node.stat):
            continue

        for stat in node.statements:
            if pred(stat):
                # Predicate holds on this graph node, so this node is ok
                break
        else:
            # Predicate does NOT hold anywhere on this graph node, this means that all of it's
            # successors must satisfy the predicate everywhere along their code paths.
            # If the node has no successors, it is the last node, and some code path failed
            if not node.next:
                return [*path, node]

            for nxt in node.next:
                if nxt not in visited:
                    todo[nxt] = [*path, node]
    return None


def _predicate_on_all_code_paths_to(
    source: MethodSummary | PropertyGetSetSummary | tf.StatementList,
    target: tf.Statement,
    pred: Callable[[tf.Statement], bool],
) -> list[ProgramNode] | None:
    """Check whether a predicate holds on all code paths to a certain node. First finds the
    desired node in the graph, then searches backwards in the same way as
    _predicate_on_all_code_paths. Returns the failing path."""
    graph = get_program_graph(source)
    tgt_node = _find_statement_node(graph, target)

    # node not reachable, so there are no code paths
    if tgt_node is None:
        return None

    todo: dict[ProgramNode, list[ProgramNode]] = {tgt_node: []}
    visited: set[ProgramNode] = set()

    def _is_node_ok(_node: ProgramNode) -> bool:
        """Check whether the given node satisfies the predicate BEFORE the target statement"""
        if _node.stat is target:
            # node statement is target, this node is NOT okay
            return False
        elif _node.stat is not None and pred(_node.stat):
            # node statement satisfies condition, node is okay
            return True

        for stat in _node.statements:
            if stat is target:
                # target itself does not count, and certainly any nodes after it don't
                # this node is NOT okay
                return False

            if pred(stat):
                # Predicate holds on this graph node, so this node is ok
                return True
        # Predicate does NOT hold anywhere on this graph node, node is NOT okay
        return False

    while todo:
        node, path = todo.popitem()
        visited.add(node)
        if not _is_node_ok(node):
            # Predicate does NOT hold anywhere on this graph node, this means that all of it's
            # successors must satisfy the predicate everywhere along their code paths.
            # If the node has no successors, it is the last node, and some code path failed
            if not node.prev:
                return [node, *path]

            for prv in node.prev:
                if prv not in visited:
                    todo[prv] = [node, *path]
    return None


def get_statements(
    obj: _Graphable | tf.Statement | None,
) -> Iterator[tf.Statement]:
    """Iterate through all (nested) statements of a method, statement list or of a single
    (possibly again nested) statement"""

    # Even though it may be slightly less efficient, we get the statements from the program
    # graph, which makes it so we do not have to keep this method and get_program_graph in
    # sync
    graph = get_program_graph(obj)
    visited: set[ProgramNode] = set()
    todo: set[ProgramNode] = {graph}

    while todo:
        node = todo.pop()
        visited.add(node)
        if node.stat is not None:
            yield node.stat
        yield from node.statements

        for nxt in node.next:
            if nxt not in visited:
                todo.add(nxt)


def _get_expressions(
    obj,
    outer: bool = True,
    include_assigned_values: bool = False,
) -> Iterator[tf.Expression]:
    """Get all expressions present in a given object. This does NOT iterate through
    subexpressions. To do that, use get_subexpressions.

    NOTE: this is a very rudimentary, and actually kind of hacky implementation for doing this,
    as we really just inspect the objects and then iterate through the data that way. Of course,
    a cleaner way of doing this would be to check each type of transformed data, and iterate
    through it that way, or to extend the transformed data classes and add a method that
    yields expressions that way."""
    assert not outer or isinstance(obj, tf.Statement)

    # don't yield expressions from substatements
    if not outer and isinstance(obj, tf.Statement):
        return
    if not include_assigned_values:
        if isinstance(obj, tf.AssignmentStatement):
            yield obj.expression
            return
        elif isinstance(obj, tf.ReferenceAssignmentStatement):
            yield obj.expression
            return
        elif isinstance(obj, tf.ForStatement):
            yield obj.from_
            yield obj.to
            for stat in obj.statements.statements:
                yield from _get_expressions(
                    stat,
                    include_assigned_values=include_assigned_values,
                    outer=True,  # allow outer again because these will be statements
                )
            return
    if isinstance(obj, tf.Expression):
        yield obj
    elif dataclasses.is_dataclass(obj):
        # all blark transform objects are dataclasses
        for field in dataclasses.fields(obj):
            yield from _get_expressions(getattr(obj, field.name), outer=False)
    elif isinstance(obj, dict):
        for val in obj.values():
            yield from _get_expressions(val, outer=False)
    elif isinstance(obj, list | tuple):
        for val in obj:
            yield from _get_expressions(val, outer=False)


def get_expressions(stat: tf.Statement, include_assigned_values: bool = False):
    yield from _get_expressions(
        stat,
        outer=True,
        include_assigned_values=include_assigned_values,
    )


def get_subexpressions(
    expr: tf.Expression,
    exclude: Callable[[tf.Expression], bool] | None = None,
    include_assigned_values: bool = False,
) -> Iterator[tf.Expression]:
    """Get all subexpressions of a given expression. Don't go any deeper if the expression is
    excluded by the provided predicate."""

    if exclude is not None and exclude(expr):
        return

    yield expr

    if isinstance(expr, tf.UnaryOperation):
        yield from get_subexpressions(expr.expr)
    elif isinstance(expr, tf.BinaryOperation):
        yield from get_subexpressions(expr.left)
        yield from get_subexpressions(expr.right)
    elif isinstance(expr, tf.ParenthesizedExpression):
        yield from get_subexpressions(expr.expr)
    elif isinstance(expr, tf.BracketedExpression):
        yield from get_subexpressions(expr.expression)
    elif isinstance(expr, tf.FunctionCall):
        # We do not really want to yield the function name as a subexpression.
        # We couldn't really do any meaningful checks on this anyway, except maybe
        # capitalization. Existence would be checked in a build anyway, and the type can not
        # easily be represented
        # yield from get_subexpressions(expr.name)  # SymbolicVariable is an expression
        for param in expr.parameters:
            assert isinstance(
                param,
                tf.OutputParameterAssignment | tf.InputParameterAssignment,
            )
            if isinstance(param, tf.OutputParameterAssignment) and not include_assigned_values:
                return
            if param.value is not None:
                yield from get_subexpressions(param.value)
    elif isinstance(expr, tf.ChainedFunctionCall):
        for call in expr.invocations:
            yield from get_subexpressions(call)
    elif isinstance(expr, tf.MultiElementVariable):
        for elt in expr.elements:
            if isinstance(elt, tf.SubscriptList):
                for subs in elt.subscripts:
                    yield from get_subexpressions(subs)
    else:
        # let's just validate that the expression is of a "leaf type" (having no subexpressions)
        # explicitly
        leaf_type = (
            tf.Literal
            | tf.Integer
            | tf.BinaryInteger
            | tf.OctalInteger
            | tf.HexInteger
            | tf.Real
            | tf.BitString
            | tf.BinaryBitString
            | tf.OctalBitString
            | tf.HexBitString
            | tf.Boolean
            | tf.Duration
            | tf.Lduration
            | tf.TimeOfDay
            | tf.LtimeOfDay
            | tf.Date
            | tf.Ldate
            | tf.DateTime
            | tf.LdateTime
            | tf.String
            | tf.DirectVariable
            | tf.Location
            | tf.SimpleVariable
        )
        assert isinstance(expr, leaf_type)


def all_subexpressions(obj: _Graphable, **kwargs) -> Iterator[tf.Expression]:
    for stat in get_statements(obj):
        for expr in get_expressions(stat):
            yield from get_subexpressions(expr, **kwargs)


def is_assignment_for(varname: str, stat: tf.Statement, adr_is_assignment: bool = True) -> bool:
    """Check whether a statement is an assignment for the given variable name. Treat any
    ADR(varname) statement as if it is being used to assign, as parsing pointer magic is hard,
    whenever adr_is_assignment is set to True (default)."""
    is_assignment = False
    if isinstance(stat, tf.AssignmentStatement):
        is_assignment = any(
            (
                (isinstance(var, tf.SimpleVariable) and streq(var.name, varname))
                # struct field assignments count as assignments
                or (isinstance(var, tf.MultiElementVariable) and streq(var.name.name, varname))
            )
            for var in stat.variables
        )
    elif isinstance(stat, tf.ReferenceAssignmentStatement):
        is_assignment = (
            isinstance(stat.variable, tf.SimpleVariable) and streq(stat.variable.name, varname)
        ) or (
            # struct field assignments count as assignments
            isinstance(stat.variable, tf.MultiElementVariable)
            and streq(stat.variable.name.name, varname)
        )
    elif isinstance(stat, tf.ForStatement):
        is_assignment = isinstance(stat.control, tf.SimpleVariable) and streq(
            stat.control.name, varname
        )

    if is_assignment:
        return True

    for expr in get_expressions(stat):
        for subexpr in get_subexpressions(expr):
            if isinstance(subexpr, tf.FunctionCall):
                # pointer magic is hard to parse, so by default we treat ADR(...) as if some
                # assignment (i.e. a memcpy to this value) is about to happen
                if adr_is_assignment:
                    is_adr = (
                        isinstance(subexpr.name, tf.SimpleVariable)
                        and streq(subexpr.name.name, "ADR")
                        and streq(subexpr.parameters[0].value.name, varname)  # type: ignore
                    )
                    if is_adr:
                        return True

                is_assignment = any(
                    isinstance(param, tf.OutputParameterAssignment)
                    and isinstance(param.value, tf.SimpleVariable)
                    and streq(param.value.name, varname)
                    for param in subexpr.parameters
                )
                if is_assignment:
                    return True
    return False


def has_assignment(
    obj: MethodSummary | PropertyGetSetSummary | tf.StatementList,
    varname: str,
) -> bool:
    """Check whether a given object (method or property getter) has a return value"""
    failing_path = _predicate_on_all_code_paths(obj, partial(is_assignment_for, varname))
    return failing_path is None


def has_assignment_before(
    stat: tf.Statement,
    meth: MethodSummary | PropertyGetSetSummary | tf.StatementList,
    varname: str,
) -> bool:
    """Check whether a given variable is assigned to before the given statement"""
    failing_path = _predicate_on_all_code_paths_to(
        meth, stat, partial(is_assignment_for, varname)
    )
    return failing_path is None
