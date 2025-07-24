"""Basic parsing of TwinCAT code using blark, in parallel."""

import concurrent.futures as fut
import copyreg
import hashlib
import pickle
from collections.abc import Iterable, Iterator
from importlib.metadata import version
from io import BytesIO
from pathlib import Path

from blark.input import BlarkCompositeSourceItem, BlarkSourceItem
from blark.parse import ParseResult, load_file_by_name, parse_item
from lark import UnexpectedCharacters
from lxml import etree

from .utils import log

logger = log.get_logger()

"""Pickling blark ParseResults requires some special attention: some objects seem to store the
original XML data (elements or entire trees), which cannot be pickled by default. I don't think
they are really used once the results have been parsed / transformed / summarized, but this does
not really have any performance indications anyway.

See the UPDATE of SO post for these pickling shananigans:
https://stackoverflow.com/questions/25991860/
"""


def _etree_unpkl(data):
    """Unpickle etree._ElementTree / etree._Element from bytes"""
    # I don't care about loading unsafe data here 🤪
    return etree.parse(BytesIO(data))  # noqa: S320


def _etree_pkl(tree: etree._ElementTree | etree._Element):
    """Pickle etree._ElementTree / etree._Element"""
    return _etree_unpkl, (etree.tostring(tree),)


copyreg.pickle(etree._ElementTree, _etree_pkl, _etree_unpkl)
copyreg.pickle(etree._Element, _etree_pkl, _etree_unpkl)


# Define pickling / unpickling functions for UnexpectedCharacters exception, which is raised
# if invalid syntax is detected in a source file. This likely indicates missing features in the
# blark grammar.
def _unexp_char_unpkl(
    pos_in_stream,
    line,
    column,
    allowed,
    considered_tokens,
    state,
    token_history,
    _terminals_by_name,
    considered_rules,
    char,
    _context,
) -> UnexpectedCharacters:
    dummy = UnexpectedCharacters.__new__(UnexpectedCharacters)
    # Bypass __init__ and manually assign
    dummy.pos_in_stream = pos_in_stream
    dummy.line = line
    dummy.column = column
    dummy.allowed = allowed
    dummy.considered_tokens = considered_tokens
    dummy.state = state
    dummy.token_history = token_history
    dummy._terminals_by_name = _terminals_by_name
    dummy.considered_rules = considered_rules
    dummy.char = char
    dummy._context = _context

    return dummy


def _unexp_char_pkl(exc: UnexpectedCharacters):
    state = (
        exc.pos_in_stream,
        exc.line,
        exc.column,
        exc.allowed,
        exc.considered_tokens,
        exc.state,
        exc.token_history,
        exc._terminals_by_name,
        exc.considered_rules,
        exc.char,
        exc._context,
    )
    return _unexp_char_unpkl, state


copyreg.pickle(UnexpectedCharacters, _unexp_char_pkl, _unexp_char_unpkl)


def get_all_source_items(file: Path) -> Iterator[BlarkSourceItem]:
    """Get all (flattened) source items for this file"""

    # there may be empty files, which of course contain no source items
    # the files seem to start with some byte marker though, so the file size is never 0...
    if file.stat().st_size < 10:  # noqa: PLR2004
        return

    for item in load_file_by_name(file):
        if isinstance(item, BlarkCompositeSourceItem):
            yield from item.parts
        else:
            yield item


def _parse_all_source_items_single(
    file: Path,
    cache_dir: Path | None = None,
    use_cache: bool = True,
) -> list[ParseResult]:
    """Parse all source items for a single file, and gather them in a list as to be able to
    pickle them for multiprocessing."""

    cache_file = None  # ok PyCharm, if this makes you happy
    if cache_dir is not None and use_cache:
        # hash source file
        # we salt this with the version of blark that we are using, as it may affect the results
        file_hash = hashlib.sha256(version("blark").encode())
        with file.open("rb") as f:
            file_hash.update(f.read())

        cache_file = cache_dir / f"{file.name}.{file_hash.hexdigest()}.pkl"
        if cache_file.exists():
            logger.info(f"Using cached file for {file.name}")
            with cache_file.open("rb") as f:
                # Wah wah! More unsafe data 🤪🤪
                return pickle.load(f)  # noqa: S301

    result = []
    logger.info(f"Parsing {file}")
    for item in get_all_source_items(file):
        result.extend(parse_item(item))

    if cache_dir is not None and use_cache:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        with cache_file.open("wb") as f:
            pickle.dump(result, f)

    return result


def parse_all_source_items(
    files: Iterable[Path],
    cache_dir: Path | None = None,
    use_cache: bool = True,
    **kwargs,
) -> Iterator[ParseResult]:
    """Load and get all source items for this list of files, in parallel. kwargs are passed to
    the ProcessPoolExecutor, one may want to pass max_workers for example."""
    futures: dict[fut.Future[list], Path] = {}
    with fut.ProcessPoolExecutor(**kwargs) as pool:
        logger.info("Submitting files for parsing...")
        for file in files:
            # yield from _parse_all_source_items_single(
            #     file, use_cache=False
            # )
            futures[
                pool.submit(
                    _parse_all_source_items_single,
                    file,
                    cache_dir=cache_dir,
                    use_cache=use_cache,
                )
            ] = file

        logger.info(f"{len(futures)} files submitted for parsing")
        for future in fut.as_completed(futures):
            result = future.result()
            logger.info(f"Parsed {futures[future].name}")
            yield from result
