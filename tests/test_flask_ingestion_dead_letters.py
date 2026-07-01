"""
Regression guard for the REMOVAL of write_dead_letter/get_db_conn from
ingestion_gateway/flask_ingestion.py (commit 858d212).

History: flask_ingestion.py originally called write_dead_letter() and
get_db_conn() to persist malformed payloads to the dead_letters Postgres
table. This was removed because incoming webhook payloads contain
TRADINGVIEW_SECRET as a passphrase field — persisting the raw payload,
even after stripping the passphrase key, kept secret material closer to
durable storage than necessary.

If write_dead_letter or get_db_conn ever come back to this module, these
tests will fail loudly to prompt a security review of why.
"""
import flask_ingestion


def test_write_dead_letter_does_not_exist():
    """write_dead_letter was deliberately removed in commit 858d212."""
    assert not hasattr(flask_ingestion, "write_dead_letter"), (
        "write_dead_letter must not exist in flask_ingestion.py — it was "
        "removed deliberately to avoid persisting secret material. "
        "See commit 858d212 for context."
    )


def test_get_db_conn_does_not_exist():
    """get_db_conn was removed alongside write_dead_letter."""
    assert not hasattr(flask_ingestion, "get_db_conn"), (
        "get_db_conn must not exist in flask_ingestion.py — the gateway "
        "is intentionally stateless with respect to Postgres. "
        "See commit 858d212 for context."
    )
