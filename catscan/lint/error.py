import linecache
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from blark.summary import DeclarationSummary, Summary
from blark.transform import Meta

from .context import Context


@dataclass(kw_only=True)
class Location:
    file: Path  # source file for the error
    function_block: str | None = None  # may not be in function block
    method: str | None = None  # may not be in method
    # todo: function
    file_line: int | None = None  # xml source line number of error
    file_col: int | None = None  # xml source line column
    file_end_col: int | None = None  # xml source end column of violating token
    source: str | None = None  # method / function block / function source code
    line: int | None = None  # line number within source code of error
    col: int | None = None  # column within source code of error
    end_col: int | None = None  # end column of violating token

    def error_line(self) -> str | None:
        """Get the violating line (if it can be found)"""
        if self.source is None and self.file_line is None:
            # no context can be determined
            return None
        elif self.source is not None and self.line is not None:
            # source and line are passed
            split_source = self.source.split("\n")
            return split_source[self.line - 1]
        elif self.file_line is not None:
            # cannot get context if no in-source line is passed, or if no source is passed
            # at all
            return linecache.getline(str(self.file), self.file_line).strip("\n")
        else:
            # no context can be determined
            return None

    def pretty(self, max_context_size: int = 2) -> str:
        # file-level context
        result = f"In {self.file}"

        # object-level context
        if self.function_block is not None:
            result += f" in function block {self.function_block}"
            if self.method is not None:
                result += f" in method {self.method}"

        # source level context
        if self.source is None and self.file_line is None:
            # no context can be determined
            return result
        elif self.source is not None and self.line is not None:
            # source and line are passed
            split_source = self.source.split("\n")
            start_line = max(self.line - max_context_size, 0)
            error_ctx_before = "\n".join(split_source[start_line: self.line])
            end_line = min(self.line + max_context_size, len(split_source))
            error_ctx_after = "\n".join(split_source[self.line: end_line])
            col, end_col = self.col, self.end_col

            result += f" in line {self.line}:{col}"
        elif self.file_line is not None:
            # cannot get context if no in-source line is passed, or if no source is passed
            # at all
            error_ctx_before = linecache.getline(str(self.file), self.file_line).strip("\n")
            error_ctx_after = None
            col, end_col = self.file_col, self.file_end_col
        else:
            # no context can be determined
            return result

        source_ctx = f"{error_ctx_before}"
        if col is not None:
            # tabs may mess up cursor spacing
            err_line = source_ctx.rsplit("\n", maxsplit=1)[-1]
            source_ctx += "\n"
            for i in range(col - 1):
                if err_line[i] == "\t":
                    source_ctx += "\t"
                else:
                    source_ctx += " "

            if end_col is not None:
                source_ctx += "^" * max(end_col - col, 1)
            else:
                # single cursor indicator
                source_ctx += "^"
        if error_ctx_after is not None:
            source_ctx += f"\n{error_ctx_after}"

        result += "\n\n" + source_ctx
        return result


@dataclass(kw_only=True)
class ErrorInfo:
    message: str
    ctx: Context | None = None
    violating: Any = None  # violating object
    meta: Meta | None = None  # meta of violating object
    source_obj: Summary | None = None  # 'parent object'
    file: Path | None = None


@dataclass(kw_only=True)
class Error:
    code: str
    message: str
    loc: Location

    @classmethod
    def from_info(
        cls,
        code: str,
        info: ErrorInfo,
    ):
        info.source_obj = (
            info.source_obj or info.ctx.current_method or info.ctx.current_function_block
        )
        info.meta = info.meta or getattr(info.violating, "meta", None)

        # source code depends on the type of violating object, declarations are in the
        # declaration source, while statements, expressions, etc. are in the implementation
        if isinstance(info.violating, DeclarationSummary):
            source = getattr(info.source_obj, "source", None)
        else:
            source = getattr(info.source_obj, "implementation_source", None)

        return Error(
            code=code,
            message=info.message,
            loc=Location(
                file=info.file or info.source_obj.filename,
                function_block=getattr(info.ctx.current_function_block, "name", None),
                method=getattr(info.ctx.current_method, "name", None),
                # todo: function
                file_line=info.meta and info.meta.line,
                file_col=info.meta and info.meta.column,
                file_end_col=info.meta and info.meta.end_column,
                source=source,
                line=info.meta and info.meta.container_line,
                col=info.meta and info.meta.container_column,
                end_col=info.meta and info.meta.container_end_column,
            ),
        )

    def pretty_print(self, prefix: str | None):
        print("\033[31m", end="")  # noqa: T201
        if prefix is not None:
            print(prefix, end="")  # noqa: T201
        print(f"{self.code}: {self.message}\033[0m")  # noqa: T201
        print(self.loc.pretty())  # noqa: T201
        print()  # noqa: T201
