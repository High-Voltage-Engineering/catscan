import copy

import pytest


@pytest.fixture(scope="function", autouse=True)
def reset_checks():
    """Fixture to ensure that lint checks in tests do not interfere with other tests"""
    import catscan.lint.base

    registered_codes = copy.deepcopy(catscan.lint.base.__REGISTERED_CODES__)
    registered_checks = copy.deepcopy(catscan.lint.base.__REGISTERED_CHECKS__)
    yield
    catscan.lint.base.__REGISTERED_CODES__ = registered_codes
    catscan.lint.base.__REGISTERED_CHECKS__ = registered_checks
