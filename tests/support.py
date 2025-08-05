import uuid
from collections.abc import Iterable
from os import PathLike
from pathlib import Path

from blark.parse import summarize

from catscan import lint
from catscan.lint.base import do_checks, get_checkable_objects
from catscan.parse import parse_all_source_items
from catscan.settings import Settings, CheckSettings


def make_settings(*, keep: Iterable[str] = ()) -> Settings:
    """Generate settings object which disables all tests, except the ones that are explicitly
    kept."""
    keep = set(keep)
    check_settings = {}
    for check in lint.list_():
        if check.code not in keep:
            check_settings[check.code] = CheckSettings(enabled=False)

    return Settings(checks=check_settings)


def get_errors(
    example: str,
    tmp_path: PathLike,
    settings: Settings,
) -> Iterable[lint.error.Error]:
    """Get errors from example source code"""
    tmp_file = Path(tmp_path) / f"Test_{uuid.uuid4()}.TcPOU"
    with tmp_file.open("w") as f:
        f.write(example)
        f.flush()

        code = summarize(list(parse_all_source_items([tmp_file], use_cache=False)))
        for obj, ctx in get_checkable_objects(code, settings):
            yield from do_checks(obj, ctx=ctx, settings=settings)


def tcpou(*args) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
      <TcPlcObject Version="1.1.0.1">
        {'\n'.join(args)}
      </TcPlcObject>
    """


def function_block(*args, name: str = "Test", decl: str = "", implementation: str = ""):
    return f"""
      <POU Name="{name}" Id="{uuid.uuid4()}" SpecialFunc="None">
        <Declaration><![CDATA[FUNCTION_BLOCK {name} {decl}]]></Declaration>
        <Implementation>
          <ST><![CDATA[{implementation}]]></ST>
        </Implementation>
        {'\n'.join(args)}
      </POU>
    """


def method(name: str = "m_Test", decl: str = "", implementation: str = ""):
    return f"""
      <Method Name="{name}" Id="{uuid.uuid4()}">
        <Declaration><![CDATA[METHOD {name}
        {decl}
        ]]></Declaration>
        <Implementation>
          <ST><![CDATA[
              {implementation}
          ]]></ST>
        </Implementation>
      </Method>
    """
