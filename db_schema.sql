-- ============================================================
-- Apex Engine — Master Database Schema
-- Idempotent: safe to run on a fresh DB or an existing one.
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ────────────────────────────────────────────────────────────
-- STRATEGIES
-- Central registry for every strategy Apex knows about.
-- param_hash enforces exact-duplicate prevention at registration.
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS strategies (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name                VARCHAR(128) UNIQUE NOT NULL,
    strategy_type       VARCHAR(64),
    timeframe           VARCHAR(16),
    asset_class         VARCHAR(32),
    parameters          JSONB DEFAULT '{}',

    -- Lifecycle
    lifecycle_state     VARCHAR(16) DEFAULT 'yellow'
                            CHECK (lifecycle_state IN ('yellow', 'green', 'red', 'grey')),
    consecutive_failures INTEGER DEFAULT 0,
    archived_at         TIMESTAMPTZ,

    -- Quality signals
    confidence_stars    SMALLINT DEFAULT 0 CHECK (confidence_stars BETWEEN 0 AND 3),
    rank_score          NUMERIC(10, 4) DEFAULT 0,

    -- Fingerprint (SHA-256 of core params — blocks exact duplicates)
    param_hash          VARCHAR(64) UNIQUE,

    -- Meta
    is_paper            BOOLEAN DEFAULT TRUE,
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Add new columns safely if this runs against an older schema
ALTER TABLE strategies ADD COLUMN IF NOT EXISTS consecutive_failures INTEGER DEFAULT 0;
ALTER TABLE strategies ADD COLUMN IF NOT EXISTS rank_score NUMERIC(10, 4) DEFAULT 0;
ALTER TABLE strategies ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;
ALTER TABLE strategies ADD COLUMN IF NOT EXISTS asset_class VARCHAR(32);
ALTER TABLE strategies ADD COLUMN IF NOT EXISTS is_paper BOOLEAN DEFAULT TRUE;
ALTER TABLE strategies ADD COLUMN IF NOT EXISTS notes TEXT;


-- ────────────────────────────────────────────────────────────
-- EVENTS
-- Every signal received, including raw payload (passphrase stripped).
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS events (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    strategy_id     UUID REFERENCES strategies(id) ON DELETE SET NULL,
    ticker          VARCHAR(16),
    action          VARCHAR(16),
    order_id        VARCHAR(128),
    signal_price    NUMERIC(18, 8),
    fill_price      NUMERIC(18, 8),
    qty             NUMERIC(18, 8),
    regime          VARCHAR(32),
    signal_time     TIMESTAMPTZ,
    fill_time       TIMESTAMPTZ DEFAULT NOW(),
    raw_payload     JSONB
);

CREATE INDEX IF NOT EXISTS idx_events_strategy_id ON events(strategy_id);
CREATE INDEX IF NOT EXISTS idx_events_fill_time   ON events(fill_time DESC);


-- ────────────────────────────────────────────────────────────
-- TRADES
-- One row per completed round-trip (open + close).
-- PnL, slippage, and MAE/MFE live here for ML training.
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS trades (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    strategy_id     UUID REFERENCES strategies(id) ON DELETE SET NULL,
    ticker          VARCHAR(16),
    direction       VARCHAR(8) CHECK (direction IN ('LONG', 'SHORT')),
    entry_event_id  UUID REFERENCES events(id),
    exit_event_id   UUID REFERENCES events(id),
    entry_price     NUMERIC(18, 8),
    exit_price      NUMERIC(18, 8),
    qty             NUMERIC(18, 8),
    pnl             NUMERIC(18, 8),
    pnl_pct         NUMERIC(10, 6),
    slippage        NUMERIC(18, 8),
    status          VARCHAR(8) DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    opened_at       TIMESTAMPTZ DEFAULT NOW(),
    closed_at       TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_trades_strategy_id ON trades(strategy_id);
CREATE INDEX IF NOT EXISTS idx_trades_status       ON trades(status);
CREATE INDEX IF NOT EXISTS idx_trades_closed_at    ON trades(closed_at DESC);


-- ────────────────────────────────────────────────────────────
-- PERFORMANCE
-- Calculated metrics per strategy. Upserted after every trade close.
-- One row per strategy (UNIQUE on strategy_id).
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS performance (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    strategy_id         UUID UNIQUE REFERENCES strategies(id) ON DELETE CASCADE,
    total_trades        INTEGER DEFAULT 0,
    winning_trades      INTEGER DEFAULT 0,
    losing_trades       INTEGER DEFAULT 0,
    win_rate            NUMERIC(6, 4) DEFAULT 0,
    avg_win             NUMERIC(18, 8) DEFAULT 0,
    avg_loss            NUMERIC(18, 8) DEFAULT 0,
    profit_factor       NUMERIC(10, 4) DEFAULT 0,
    total_pnl           NUMERIC(18, 8) DEFAULT 0,
    max_drawdown        NUMERIC(10, 6) DEFAULT 0,
    sharpe_ratio        NUMERIC(10, 4) DEFAULT 0,
    sortino_ratio       NUMERIC(10, 4) DEFAULT 0,
    expectancy          NUMERIC(18, 8) DEFAULT 0,
    avg_slippage        NUMERIC(18, 8) DEFAULT 0,
    last_calculated_at  TIMESTAMPTZ DEFAULT NOW()
);


-- ────────────────────────────────────────────────────────────
-- MARKET REGIMES
-- History of detected market conditions. Used by ranking engine
-- and will feed ML regime-aware models in Phase 4.
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS market_regimes (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    regime_label        VARCHAR(32),    -- trending_up | trending_down | choppy | volatile
    adx_value           NUMERIC(10, 4),
    trend_direction     VARCHAR(8),     -- up | down
    volatility_label    VARCHAR(16),    -- high | normal | low
    detected_at         TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_market_regimes_time ON market_regimes(detected_at DESC);


-- ────────────────────────────────────────────────────────────
-- DEAD LETTERS
-- Failed signals, malformed payloads, and processing errors.
-- Never deleted — reviewed manually, used for debugging + ML.
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dead_letters (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source          VARCHAR(64),        -- which service produced this
    raw_payload     JSONB,
    error_message   TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dead_letters_time ON dead_letters(created_at DESC);


-- ────────────────────────────────────────────────────────────
-- LEGACY TABLES (preserved, renamed — data never deleted)
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS legacy_execution_ledger (
    execution_id    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    timestamp       TIMESTAMPTZ NOT NULL,
    strategy_id     VARCHAR(64) NOT NULL,
    symbol          VARCHAR(16) NOT NULL,
    direction       VARCHAR(10) NOT NULL,
    execution_price NUMERIC(18, 8) NOT NULL,
    quantity        NUMERIC(18, 8) NOT NULL,
    run_id          UUID,
    is_simulated    BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS legacy_strategy_signals (
    timestamp       TIMESTAMPTZ NOT NULL,
    strategy_id     VARCHAR(64) NOT NULL,
    symbol          VARCHAR(16) NOT NULL,
    signal_value    SMALLINT NOT NULL,
    stop_loss       NUMERIC(18, 8),
    take_profit     NUMERIC(18, 8),
    metadata        JSONB,
    PRIMARY KEY (timestamp, strategy_id, symbol)
);
