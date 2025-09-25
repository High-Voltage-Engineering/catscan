@echo off

rem used to be lint:fmt
uvx --from "black==25.1.0" black .
uvx --from "ruff==0.11.13" ruff check --fix .
rem used to be lint:style
uvx --from "ruff==0.11.13" ruff check .
uvx --from "black==25.1.0" black --check --diff .
