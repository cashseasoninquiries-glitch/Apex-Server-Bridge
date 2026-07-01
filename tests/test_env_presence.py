"""
Tests for environment variable documentation/presence (Master Task Order 15.14).

Drift guard — catches when someone adds an os.getenv() call to a service
but forgets to document it in .env.example, or vice versa.
"""
import re
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent

SERVICE_FILES = [
    ROOT_DIR / "execution_engine.py",
    ROOT_DIR / "recorder" / "recorder.py",
    ROOT_DIR / "discord_notifier.py",
    ROOT_DIR / "performance_calculator.py",
    ROOT_DIR / "lifecycle_engine.py",
    ROOT_DIR / "regime_detector.py",
    ROOT_DIR / "ranking_engine.py",
    ROOT_DIR / "strategy_mvp.py",
    ROOT_DIR / "strategy_registry.py",
    ROOT_DIR / "ingestion_gateway" / "flask_ingestion.py",
]

ENV_EXAMPLE = ROOT_DIR / ".env.example"
DOCKER_COMPOSE = ROOT_DIR / "docker-compose.yml"

REQUIRED_ENV_VARS = {
    "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB",
    "REDIS_PASSWORD",
    "MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD",
    "CLICKHOUSE_DB", "CLICKHOUSE_USER", "CLICKHOUSE_PASSWORD",
    "ALPACA_API_KEY", "ALPACA_SECRET_KEY",
    "TRADINGVIEW_SECRET",
}

OPTIONAL_ENV_VARS = {
    "REDIS_HOST", "POSTGRES_HOST",
    "ALPACA_PAPER_TRADING", "DEFAULT_ORDER_QTY", "FILL_TIMEOUT_SECS",
    "DISCORD_WEBHOOK_URL",
    "STRATEGY_MVP_ID", "STRATEGY_MVP_TICKER", "STRATEGY_MVP_FAST_PERIOD",
    "STRATEGY_MVP_SLOW_PERIOD", "STRATEGY_MVP_POLL_SECONDS",
}

ALL_KNOWN_VARS = REQUIRED_ENV_VARS | OPTIONAL_ENV_VARS

_GETENV_PATTERN = re.compile(
    r"os\.getenv\(\s*['\"]([A-Z_][A-Z0-9_]*)['\"]"
    r"|os\.environ\[\s*['\"]([A-Z_][A-Z0-9_]*)['\"]\s*\]"
    r"|os\.environ\.get\(\s*['\"]([A-Z_][A-Z0-9_]*)['\"]"
)

_COMPOSE_VAR_PATTERN = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


def _vars_referenced_in(path):
    text = path.read_text()
    found = set()
    for match in _GETENV_PATTERN.finditer(text):
        found.add(next(g for g in match.groups() if g))
    return found


def _vars_documented_in_env_example():
    text = ENV_EXAMPLE.read_text()
    documented = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            documented.add(line.split("=", 1)[0].strip())
    return documented


def _vars_referenced_in_docker_compose():
    text = DOCKER_COMPOSE.read_text()
    return set(_COMPOSE_VAR_PATTERN.findall(text))


@pytest.mark.parametrize("path", SERVICE_FILES, ids=lambda p: p.name)
def test_every_env_var_referenced_in_a_service_is_in_the_canonical_list(path):
    referenced = _vars_referenced_in(path)
    undocumented = referenced - ALL_KNOWN_VARS
    assert not undocumented, (
        f"{path.name} references env var(s) {undocumented} not in "
        f"REQUIRED_ENV_VARS or OPTIONAL_ENV_VARS. Add them there and to .env.example."
    )


def test_every_var_docker_compose_interpolates_is_in_the_canonical_list():
    referenced = _vars_referenced_in_docker_compose()
    undocumented = referenced - ALL_KNOWN_VARS
    assert not undocumented, (
        f"docker-compose.yml references {undocumented}, not in the canonical env var list."
    )


def test_env_example_file_exists():
    assert ENV_EXAMPLE.exists(), ".env.example is missing"


def test_every_required_var_is_documented_in_env_example():
    documented = _vars_documented_in_env_example()
    missing = REQUIRED_ENV_VARS - documented
    assert not missing, f".env.example is missing required var(s): {missing}"


def test_no_stale_vars_in_env_example():
    documented = _vars_documented_in_env_example()
    stale = documented - ALL_KNOWN_VARS
    assert not stale, f".env.example documents var(s) no longer referenced anywhere: {stale}"


def test_no_required_secret_has_a_committed_value():
    text = ENV_EXAMPLE.read_text()
    exempt = {"POSTGRES_USER", "POSTGRES_DB"}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key in REQUIRED_ENV_VARS and key not in exempt:
            assert value == "", f"{key} should be blank in .env.example, found a committed value"


def test_flask_ingestion_redis_client_now_uses_env_auth():
    """Regression guard for the Redis auth bug fixed in commit 940af2d."""
    text = (ROOT_DIR / "ingestion_gateway" / "flask_ingestion.py").read_text()
    assert "REDIS_PASSWORD" in text, "flask_ingestion.py should read REDIS_PASSWORD from the environment"
    redis_call = text[text.index("redis.Redis("):text.index("redis.Redis(") + 200]
    assert "password" in redis_call, "redis.Redis(...) call must pass password= or AUTH will fail"
