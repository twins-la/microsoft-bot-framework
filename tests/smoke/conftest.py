"""Shared fixtures for the Microsoft Bot Framework twin smoke tests.

Spins the twin up in-process via Flask's test client, with SQLite storage
and an in-process SQLiteTenantStore. No Docker or external services
needed.
"""

import base64
import os
import sys

import pytest

# twins_microsoft_bot_framework_local sibling lives inside this repo; put
# the repo root on sys.path so it can import from a checkout that has not
# been pip-installed.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from twins_local.tenants import (  # noqa: E402
    SQLiteTenantStore,
    ensure_default_tenant,
    generate_tenant_id,
    generate_tenant_secret,
    hash_secret,
)
from twins_microsoft_bot_framework.app import create_app  # noqa: E402
from twins_microsoft_bot_framework.tokens import clear_jwks_cache  # noqa: E402
from twins_microsoft_bot_framework_local.storage_sqlite import SQLiteStorage  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_jwks_cache():
    """The bot half caches JWKS docs by URL; tests rotate keys per session,
    so each test gets a fresh cache."""
    clear_jwks_cache()
    yield
    clear_jwks_cache()


@pytest.fixture
def tenant_store(tmp_path):
    store = SQLiteTenantStore(db_path=str(tmp_path / "tenants.sqlite3"))
    ensure_default_tenant(store)
    return store


@pytest.fixture
def storage(tmp_path):
    """Twin's SQLiteStorage backing the in-process app. Exposed as a
    fixture so tests can read or pre-populate storage state directly
    (e.g., the channel's signing key for validation-failure tests).
    """
    return SQLiteStorage(db_path=str(tmp_path / "test_twin.db"))


@pytest.fixture
def twin_app(storage, tenant_store):
    app = create_app(
        storage=storage,
        tenants=tenant_store,
        config={"base_url": "http://localhost:8080"},
    )
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(twin_app):
    return twin_app.test_client()


@pytest.fixture
def tenant(tenant_store):
    tenant_id = generate_tenant_id()
    tenant_secret = generate_tenant_secret()
    tenant_store.create_tenant(
        tenant_id=tenant_id,
        secret_hash=hash_secret(tenant_secret),
        friendly_name="Test Tenant",
    )
    return {"tenant_id": tenant_id, "tenant_secret": tenant_secret}


@pytest.fixture
def tenant_headers(tenant):
    creds = base64.b64encode(
        f"{tenant['tenant_id']}:{tenant['tenant_secret']}".encode()
    ).decode()
    return {"Authorization": f"Basic {creds}"}
