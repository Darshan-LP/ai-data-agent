"""
Shared pytest fixtures.

Validator tests do not require a database.
Integration tests can use these fixtures to check
whether PostgreSQL is available.
"""

import pytest

from app.config import get_settings
from app.db import readonly_engine, ping


@pytest.fixture(scope="session")
def settings():
    return get_settings()


@pytest.fixture(scope="session")
def readonly():
    engine = readonly_engine()

    if not ping(engine):
        pytest.skip("Postgres not reachable; skipping integration test.")

    return engine