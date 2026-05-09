"""Concurrency test for the singleton signing-key cold-start race.

Closes twins-la/microsoft-bot-framework#2: two concurrent gunicorn pre-fork
workers booting against a fresh deploy must end up with exactly one stored
keypair, not one per worker. The fix is the atomic
``storage.get_or_create_signing_key`` primitive.
"""

import sqlite3
import threading

import pytest

from twins_microsoft_bot_framework.crypto import ensure_keypair
from twins_microsoft_bot_framework_local.storage_sqlite import SQLiteStorage


@pytest.fixture
def storage(tmp_path):
    return SQLiteStorage(db_path=str(tmp_path / "race_test.db"))


def test_ensure_keypair_serializes_concurrent_first_calls(storage):
    """N threads calling ensure_keypair on a fresh storage must yield:
    (a) exactly one row in the signing_keys table,
    (b) every returned dict carrying the same kid (the canonical first key).
    """
    n_threads = 16
    results: list[dict] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(n_threads)

    def worker():
        try:
            barrier.wait()
            results.append(ensure_keypair(storage))
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"workers raised: {errors}"
    assert len(results) == n_threads

    kids = {r["kid"] for r in results}
    assert len(kids) == 1, f"expected one canonical kid, got {len(kids)}: {kids}"

    conn = sqlite3.connect(str(storage._db_path))
    try:
        count = conn.execute("SELECT COUNT(*) FROM signing_keys").fetchone()[0]
    finally:
        conn.close()
    assert count == 1, f"expected one signing_keys row, got {count}"


def test_ensure_keypair_is_idempotent_on_steady_state(storage):
    """Sequential calls after the key exists must return the same dict each time."""
    first = ensure_keypair(storage)
    second = ensure_keypair(storage)
    third = ensure_keypair(storage)
    assert first["kid"] == second["kid"] == third["kid"]
    assert first["private_pem"] == second["private_pem"] == third["private_pem"]
