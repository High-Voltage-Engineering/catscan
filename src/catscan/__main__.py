import fnmatch
import glob
import importlib.util
import sys
import textwrap
from pathlib import Path

import click
from blark.parse import ParseResult, summarize
from click import Context

from . import lint
from .parse import parse_all_source_items
from .settings import load_settings
from .utils import log

logger = log.get_logger()
DEFAULT_CACHE_DIR = Path(".catscan")


def _load_plugins(plugins: tuple[Path]):
    """Load catscan plugins from paths. This is done by simply importing the module. The
    @lint_check decorator should then automatically register new plugins."""

    def import_module_from_path(path: Path):
        logger.info(f"Loading plugin from {path}")
        spec = importlib.util.spec_from_file_location(path.stem, str(path))
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

    def recursively_import(path: Path):
        """Recursively import modules from a directory or file."""

        if path.is_file() and path.suffix == ".py":
            # Simple single-file python module
            import_module_from_path(path)
        elif path.is_dir():
            init_file = path / "__init__.py"
            if init_file.exists():
                # directory-based python module
                import_module_from_path(init_file)
            else:
                # load modules recursively
                for sub_path in path.iterdir():
                    recursively_import(sub_path)

    for plugin in plugins:
        recursively_import(plugin)


@click.group()
@click.option(
    "-s",
    "--settings",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Optional JSON settings file",
)
@click.option(
    "--plugin",
    "plugins",
    multiple=True,
    type=click.Path(exists=True, dir_okay=True, path_type=Path),
    help="Optional JSON settings file",
)
@click.pass_context
def main(
    ctx: Context,
    settings: Path | None,
    plugins: tuple[Path],
):
    _load_plugins(plugins)
    ctx.obj = load_settings(settings)


@main.command("list")
@click.pass_context
def list_(_ctx: Context):
    """List all registered checks"""
    code_width = 7  # maximum code width (can just be computed from lint.CODE_PATT)
    doc_indent = 4
    for check in lint.list_():
        click.echo(f"{check.code.ljust(code_width)} {check.name}:")
        wrapped_doc = textwrap.fill(
            check.doc,
            width=96,
            initial_indent=" " * (code_width + 1 + doc_indent),
            subsequent_indent=" " * (code_width + 1),
        )

        click.echo(wrapped_doc)


@main.command("lint")
@click.option(
    "--use-cache/--no-cache", default=True, help="Enable or disable caching (default: enabled)"
)
@click.option(
    "--cache-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=DEFAULT_CACHE_DIR,
    show_default=True,
    help="Directory to store cache data",
)
@click.option(
    "-r",
    "--root-dir",
    "root_dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("."),
    show_default=True,
    help="Root directory to scan patterns from",
)
@click.option(
    "-e",
    "--exclude",
    "excludes",
    multiple=True,
    help="Glob pattern(s) to exclude (may be given multiple times)",
)
@click.option(
    "-p",
    "--pattern",
    "patterns",
    multiple=True,
    required=True,
    help="Glob pattern(s) to include (shell-safe, may be given multiple times)",
)
@click.pass_context
def lint_(
    ctx: Context,
    use_cache: bool,
    cache_dir: Path,
    root_dir: Path,
    excludes: tuple[str],
    patterns: tuple[str],
) -> None:
    """Main lint command"""
    # for testing, you may want to override the patterns like so:
    # patterns = ("**/FB_MOD_Base.TcPOU",)
    files = set()
    for pattern in patterns:
        files |= set(map(Path, glob.glob(pattern, root_dir=root_dir, recursive=True)))

    files = {
        file for file in files if not any(fnmatch.fnmatch(str(file), excl) for excl in excludes)
    }

    logger.info(
        f"Loading {len(files)} source files based on {len(patterns)} patterns "
        f"and {len(excludes)} exclude patterns"
    )
    results: list[ParseResult] = []
    results.extend(parse_all_source_items(files, cache_dir=cache_dir, use_cache=use_cache))

    logger.info("Summarizing...")
    summary = summarize(results, squash=False)

    logger.info("Linting...")
    exit_code = lint.lint(summary, ctx.obj)
    sys.exit(exit_code)


if __name__ == "__main__":
    main(windows_expand_args=False)
