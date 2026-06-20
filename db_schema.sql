-- ============================================================
-- Apex Engine — Master Database Schema
-- Ground truth as of 2026-06-20, verified directly against the
-- live apex_vault database (container: apex_postgres_vault) via
-- \d on every table. Idempotent: safe to run on a fresh DB
-- (creates everything from scratch) or an existing one (IF NOT
-- EXISTS skips anything already applied).
--
-- NOTE: this rewrite intentionally matches what is ACTUALLY
-- live, not the original aspirational design. Several CHECK
-- constraints, secondary indexes, and ON DELETE behaviors that
-- earlier versions of this file assumed were never actually
-- applied to the production database. Those gaps are called
-- out inline below rather than silently reintroduced here.
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
-- gen_random_uuid() used below is built into Postgres core since
-- v13 and needs no extension. uuid-ossp is only needed for
-- uuid_generate_v4(), used by the legacy tables at the bottom.

-- ────────────────────────────────────────────────────────────
-- STRATEGIES
-- Central registry for every strategy Apex knows about.
-- param_hash enforces exact-duplicate prevention at registration.
-- NOTE: "name" has no UNIQUE constraint live, despite earlier
-- versions of this file assuming one. Only param_hash is unique.
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS strategies (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                    VARCHAR(255) NOT NULL,
    strategy_type           VARCHAR(100) NOT NULL,
    parameters              JSONB NOT NULL,
    timeframe               VARCHAR(20) NOT NULL,
    asset_class             VARCHAR(50) NOT NULL,

    -- Status / lifecycle
    status                  VARCHAR(20) DEFAULT 'active',
    lifecycle_state         VARCHAR(20) DEFAULT 'yellow',
    failure_reason          VARCHAR(50),
    consecutive_failures    INTEGER DEFAULT 0,
    archived_at             TIMESTAMPTZ,

    -- Quality signals
    confidence_stars        INTEGER DEFAULT 0,
    rank_score              NUMERIC(10, 4) DEFAULT 0,

    -- Fingerprint (hash of core params — blocks exact duplicates)
    param_hash              VARCHAR(64) UNIQUE,

    -- Meta
    is_paper                BOOLEAN DEFAULT TRUE,
    notes                   TEXT,
    created_at              TIMESTAMPTZ DEFAULT NOW()
);


-- ────────────────────────────────────────────────────────────
-- EVENTS
-- Every signal received, including raw payload.
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id     UUID REFERENCES strategies(id),
    ticker          VARCHAR(20) NOT NULL,
    action          VARCHAR(20) NOT NULL,
    signal_price    NUMERIC(12, 4),
    quantity        NUMERIC(12, 4),
    source          VARCHAR(20) NOT NULL,
    raw_payload     JSONB,
    received_at     TIMESTAMPTZ DEFAULT NOW(),
    market_regime   VARCHAR(20),
    regime_vix      NUMERIC(8, 4),
    notes           TEXT
);


-- ────────────────────────────────────────────────────────────
-- TRADES
-- One row per round-trip (open or closed).
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS trades (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id     UUID REFERENCES strategies(id),
    entry_event_id  UUID REFERENCES events(id),
    exit_event_id   UUID REFERENCES events(id),
    ticker          VARCHAR(20) NOT NULL,
    direction       VARCHAR(10) NOT NULL,
    entry_price     NUMERIC(12, 4) NOT NULL,
    exit_price      NUMERIC(12, 4),
    quantity        NUMERIC(12, 4) NOT NULL,
    pnl             NUMERIC(12, 4),
    pnl_pct         NUMERIC(8, 4),
    entry_at        TIMESTAMPTZ NOT NULL,
    exit_at         TIMESTAMPTZ,
    duration_mins   INTEGER,
    status          VARCHAR(20) DEFAULT 'open',
    alpaca_order_id VARCHAR(255),
    entry_regime    VARCHAR(20),
    exit_regime     VARCHAR(20),
    is_paper        BOOLEAN DEFAULT TRUE
);


-- ────────────────────────────────────────────────────────────
-- PERFORMANCE
-- Calculated metrics per strategy. Upserted after every trade
-- close. One row per strategy — strategy_id is UNIQUE (Task #54,
-- confirmed live as "performance_strategy_id_key").
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS performance (
    id                              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id                     UUID NOT NULL UNIQUE REFERENCES strategies(id),
    last_calculated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    period_start                    TIMESTAMPTZ,
    period_end                      TIMESTAMPTZ,
    total_trades                    INTEGER DEFAULT 0,
    winning_trades                  INTEGER DEFAULT 0,
    losing_trades                   INTEGER DEFAULT 0,
    win_rate                        NUMERIC(6, 4),
    avg_win                         NUMERIC(8, 4),
    avg_loss                        NUMERIC(8, 4),
    profit_factor                   NUMERIC(8, 4),
    sharpe_ratio                    NUMERIC(8, 4),
    max_drawdown                    NUMERIC(8, 4),
    total_pnl                       NUMERIC(14, 4),
    expectancy                      NUMERIC(8, 4),
    is_statistically_significant    BOOLEAN DEFAULT FALSE,
    confidence_stars                SMALLINT DEFAULT 0,
    sortino_ratio                   NUMERIC,
    avg_slippage                    NUMERIC
);


-- ────────────────────────────────────────────────────────────
-- MARKET REGIMES
-- History of detected market conditions. Used by ranking engine.
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS market_regimes (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    regime_label        VARCHAR(32),
    adx_value           NUMERIC(10, 4),
    trend_direction     VARCHAR(8),
    volatility_label    VARCHAR(16),
    detected_at         TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_market_regimes_time ON market_regimes(detected_at DESC);


-- ────────────────────────────────────────────────────────────
-- DEAD LETTERS
-- Failed signals, malformed payloads, and processing errors.
-- Never deleted — reviewed manually.
-- NOTE: raw_payload is TEXT live (not JSONB), and the timestamp
-- column is named received_at (not created_at).
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dead_letters (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    received_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source          VARCHAR(50),
    raw_payload     TEXT,
    error_message   TEXT,
    retry_count     INTEGER DEFAULT 0,
    resolved        BOOLEAN DEFAULT FALSE,
    resolved_at     TIMESTAMPTZ
);


-- ────────────────────────────────────────────────────────────
-- LEGACY TABLES — ORPHANED, NOT WIRED INTO ANY CURRENT SERVICE
-- Confirmed via repo-wide grep (2026-06-20): zero references in
-- any .py file. Hold only a handful of stale rows from an
-- earlier prototype architecture (1 row / 13 rows respectively
-- as of this writing). Kept rather than dropped — same
-- philosophy as dead_letters: reviewed manually, never silently
-- deleted. Flagged for a future decision on whether to archive
-- or drop entirely.
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS legacy_execution_ledger (
    execution_id    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    "timestamp"     TIMESTAMPTZ NOT NULL,
    strategy_id     VARCHAR(64) NOT NULL,
    symbol          VARCHAR(16) NOT NULL,
    direction       VARCHAR(10) NOT NULL CHECK (direction IN ('BUY', 'SELL', 'LIQUIDATE')),
    execution_price NUMERIC(18, 8) NOT NULL,
    quantity        NUMERIC(18, 8) NOT NULL,
    run_id          UUID NOT NULL,
    is_simulated    BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_execution_time ON legacy_execution_ledger("timestamp" DESC);

CREATE TABLE IF NOT EXISTS legacy_strategy_signals (
    "timestamp"     TIMESTAMPTZ NOT NULL,
    strategy_id     VARCHAR(64) NOT NULL,
    symbol          VARCHAR(16) NOT NULL,
    signal_value    SMALLINT NOT NULL CHECK (signal_value IN (-1, 0, 1)),
    stop_loss       NUMERIC(18, 8),
    take_profit     NUMERIC(18, 8),
    metadata        JSONB,
    PRIMARY KEY ("timestamp", strategy_id, symbol)
);

CREATE INDEX IF NOT EXISTS idx_signals_time_strat ON legacy_strategy_signals(strategy_id, "timestamp" DESC);


-- ============================================================
-- KNOWN GAPS vs. ORIGINAL DESIGN (documented, not silently fixed)
-- These were assumed/intended at some point but are NOT present
-- on the live database as of this writing. Left out of this file
-- so it stays an honest mirror of reality. Revisit deliberately
-- if/when desired:
--   - No CHECK constraints on strategies.lifecycle_state,
--     strategies.confidence_stars, trades.direction, or
--     trades.status (core tables have zero CHECK constraints
--     live; only the two legacy tables do).
--   - No secondary indexes on events or trades (e.g. no index on
--     strategy_id, status, or timestamp columns) — every lookup
--     against those tables is currently a full table scan.
--   - Foreign keys on events/trades/performance use the Postgres
--     default NO ACTION on delete, not CASCADE/SET NULL.
-- ============================================================
