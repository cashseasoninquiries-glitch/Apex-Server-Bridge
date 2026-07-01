"""
Shared pytest fixtures for the Apex test suite.

Service modules (flask_ingestion.py, execution_engine.py, recorder.py, etc.)
are plain scripts, not an installed package. `pythonpath` in pytest.ini
already points at the repo root, ingestion_gateway/, and recorder/, so
`import flask_ingestion` / `import execution_engine` / `import recorder`
work directly from any test file. This conftest just adds the same paths
defensively (in case pytest.ini config is ever bypassed) and provides
fixtures that every test importing those modules will need.
"""
import os
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent

for _sub in ("", "ingestion_gateway", "recorder"):
    _path = str(ROOT_DIR / _sub) if _sub else str(ROOT_DIR)
    if _path not in sys.path:
        sys.path.insert(0, _path)

# flask_ingestion.py fails closed (sys.exit(1)) at MODULE IMPORT time if
# TRADINGVIEW_SECRET isn't set. Pytest imports test modules during
# collection, before any fixture runs, so a fixture-based env var alone
# would be too late and would crash collection. Set this directly in the
# process environment as soon as conftest.py loads (which happens before
# any test_*.py file is collected) so `import flask_ingestion` never
# trips the fail-closed check during test runs.
os.environ.setdefault("TRADINGVIEW_SECRET", "test-secret-do-not-use-in-prod")

# execution_engine.py constructs TradingClient at MODULE IMPORT time.
# Setting dummy non-None values here guarantees import never trips over
# a None where the SDK expects a string.
os.environ.setdefault("ALPACA_API_KEY", "test-alpaca-key-do-not-use-in-prod")
os.environ.setdefault("ALPACA_SECRET_KEY", "test-alpaca-secret-do-not-use-in-prod")

# redis.Redis(...) and psycopg2.connect(...) are only ever invoked lazily
# so these aren't strictly required for import to succeed — set anyway so
# accidental real-DB/real-Redis calls fail loudly with an auth error.
os.environ.setdefault("POSTGRES_PASSWORD", "test-postgres-password")
os.environ.setdefault("REDIS_PASSWORD", "test-redis-password")


@pytest.fixture(autouse=True)
def tradingview_secret_env(monkeypatch):
    """
    Per-test safety net: ensures every test starts with the same known
    value, and lets tests that specifically want to exercise the
    'secret missing' path override with monkeypatch.delenv.
    """
    monkeypatch.setenv("TRADINGVIEW_SECRET", "test-secret-do-not-use-in-prod")


@pytest.fixture
def fake_redis(monkeypatch):
    """
    Minimal in-memory stand-in for redis.Redis, just covering the calls
    the Apex services actually use (lpush, lrem, get/set).
    """

    class _FakeRedis:
        def __init__(self):
            self.lists = {}
            self.kv = {}

        def lpush(self, key, value):
            self.lists.setdefault(key, []).insert(0, value)
            return len(self.lists[key])

        def rpush(self, key, value):
            self.lists.setdefault(key, []).append(value)
            return len(self.lists[key])

        def lrem(self, key, count, value):
            lst = self.lists.get(key, [])
            removed = 0
            while value in lst and (count == 0 or removed < abs(count)):
                lst.remove(value)
                removed += 1
            return removed

        def lrange(self, key, start, end):
            lst = self.lists.get(key, [])
            if end == -1:
                return lst[start:]
            return lst[start:end + 1]

        def get(self, key):
            return self.kv.get(key)

        def set(self, key, value):
            self.kv[key] = value
            return True

    return _FakeRedis()
