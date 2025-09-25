import io
from pathlib import Path
from typing import Any, TypeVar

from pydantic import TypeAdapter
from ruamel.yaml import YAML

# Shared YAML
_yaml = YAML()
_T = TypeVar("_T")


def load(path: Path | io.IOBase, as_type: type[_T] | None = None) -> _T or Any:
    """
    Loads a YAML file

    :param path:        the YAML file
    :param as_type:     load the YAML file as the given type, or just return the data
    :return:            The YAML file as an object
    """
    if isinstance(path, Path):
        with path.open("r") as stream:
            data = _yaml.load(stream)
    else:
        data = _yaml.load(path)

    if as_type is None:
        return data
    return TypeAdapter(as_type).validate_python(data)


def save(path: Path, data: Any) -> None:
    """
    Loads a YAML file

    :param path:        the YAML file
    :param data:        The data to save
    :return:            The YAML file as an object
    """
    with path.open("w") as stream:
        return _yaml.dump(data, stream)
