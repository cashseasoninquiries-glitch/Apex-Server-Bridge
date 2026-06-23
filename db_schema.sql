-- ============================================================
-- Apex Engine — Master Database Schema
-- Ground truth as of 2026-06-23, verified directly against the
-- live apex_vault database (container: apex_postgres_vault) via
-- \d on every table, immediately after applying
-- db_migration_2026_06_21_future_proofing.sql. Idempotent: safe
-- to run on a fresh DB (creates everything from scratch) or an
-- existing one (IF NOT EXISTS skips anything already applied).
--
-- NOTE: this rewrite intentionally matches what is ACTUALLY
-- live, not the original aspirational design. Several CHECK
-- constraints and ON DELETE behaviors that earlier versions of
-- this file assumed were never actually applied to the
-- production database. Those gaps are called out inline below
-- rather than silently reintroduced here. (The secondary-index
-- gap from the previous version of this file IS now resolved —
-- see EVENTS and TRADES below.)
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
    created_at              TIMESTAMPTZ DEFAULT NOW(),

    -- Added 2026-06-21 (future-proofing migration)
    owner_id                UUID,
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON COLUMN strategies.owner_id IS
  'Future multi-tenant owner/tenant identifier. NULL = system-owned (current solo-trader phase). Not yet enforced by any FK — user/billing DB does not exist yet.';


-- ────────────────────────────────────────────────────────────
-- EVENTS
-- Every signal received, including raw payload.
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS events (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id         UUID REFERENCES strategies(id),
    ticker              VARCHAR(32) NOT NULL,
    action              VARCHAR(20) NOT NULL,
    signal_price        NUMERIC(18, 8),
    quantity            NUMERIC(18, 8),
    source              VARCHAR(20) NOT NULL,
    raw_payload         JSONB,
    received_at         TIMESTAMPTZ DEFAULT NOW(),
    market_regime       VARCHAR(20),
    regime_vix          NUMERIC(8, 4),
    notes               TEXT,

    -- Added 2026-06-21 (future-proofing migration)
    broker              VARCHAR(50) DEFAULT 'alpaca',
    currency            VARCHAR(10) DEFAULT 'USD',
    external_signal_id  VARCHAR(255),
    source_signal_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_events_strategy     ON events(strategy_id);
CREATE INDEX IF NOT EXISTS idx_events_received_at  ON events(received_at DESC);

COMMENT ON COLUMN events.external_signal_id IS
  'Placeholder for a future idempotency/dedupe key (e.g. webhook delivery ID). Nullable, no UNIQUE constraint yet — decide the real key once actual ingestion payload structure is confirmed.';

COMMENT ON COLUMN events.source_signal_at IS
  'Timestamp the source/strategy claims the signal occurred, extracted from raw_payload if present. Distinct from received_at (our system arrival time) — lets us measure source-to-ingestion latency and detect out-of-order or delayed delivery without guessing. Nullable: not every source payload will carry one.';


-- ────────────────────────────────────────────────────────────
-- TRADES
-- One row per round-trip (open or closed).
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS trades (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id     UUID REFERENCES strategies(id),
    entry_event_id  UUID REFERENCES events(id),
    exit_event_id   UUID REFERENCES events(id),
    ticker          VARCHAR(32) NOT NULL,
    direction       VARCHAR(10) NOT NULL,
    entry_price     NUMERIC(18, 8) NOT NULL,
    exit_price      NUMERIC(18, 8),
    quantity        NUMERIC(18, 8) NOT NULL,
    pnl             NUMERIC(18, 8),
    pnl_pct         NUMERIC(8, 4),
    entry_at        TIMESTAMPTZ NOT NULL,
    exit_at         TIMESTAMPTZ,
    duration_mins   INTEGER,
    status          VARCHAR(20) DEFAULT 'open',
    alpaca_order_id VARCHAR(255),
    entry_regime    VARCHAR(20),
    exit_regime     VARCHAR(20),
    is_paper        BOOLEAN DEFAULT TRUE,

    -- Added 2026-06-21 (future-proofing migration)
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    broker          VARCHAR(50) DEFAULT 'alpaca',
    currency        VARCHAR(10) DEFAULT 'USD'
);

CREATE INDEX IF NOT EXISTS idx_trades_strategy  ON trades(strategy_id);
CREATE INDEX IF NOT EXISTS idx_trades_status    ON trades(status);
CREATE INDEX IF NOT EXISTS idx_trades_entry_at  ON trades(entry_at DESC);


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
    avg_win                         NUMERIC(18, 8),
    avg_loss                        NUMERIC(18, 8),
    profit_factor                   NUMERIC(8, 4),
    sharpe_ratio                    NUMERIC(8, 4),
    max_drawdown                    NUMERIC(8, 4),
    total_pnl                       NUMERIC(18, 8),
    expectancy                      NUMERIC(8, 4),
    is_statistically_significant    BOOLEAN DEFAULT FALSE,
    confidence_stars                SMALLINT DEFAULT 0,
    sortino_ratio                   NUMERIC,
    avg_slippage                    NUMERIC,

    -- Added 2026-06-21 (future-proofing migration)
    updated_at                      TIMESTAMPTZ DEFAULT NOW()
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

-- Added 2026-06-21 (future-proofing migration) — partial index,
-- only covers the unresolved backlog rather than the full table.
CREATE INDEX IF NOT EXISTS idx_dead_letters_unresolved
  ON dead_letters(received_at DESC) WHERE resolved = FALSE;


-- ────────────────────────────────────────────────────────────
-- STRATEGY_TRIALS
-- Added 2026-06-21 (future-proofing migration). Every backtested
-- parameter configuration tested per strategy, not just the ones
-- that got promoted. Feeds DSR/PBO/GT-Score — those calculations
-- need the full search space, not just the survivorship-biased
-- winners.
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS strategy_trials (
    id                              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id                     UUID NOT NULL REFERENCES strategies(id) ON DELETE RESTRICT,
    trial_number                    INTEGER,
    parameters                      JSONB NOT NULL,
    param_hash                      VARCHAR(64),
    dataset_start                   TIMESTAMPTZ,
    dataset_end                     TIMESTAMPTZ,
    split_type                      VARCHAR(20),
    total_trades                    INTEGER DEFAULT 0,
    win_rate                        NUMERIC(6, 4),
    sharpe_ratio                    NUMERIC(8, 4),
    sortino_ratio                   NUMERIC(8, 4),
    max_drawdown                    NUMERIC(8, 4),
    profit_factor                   NUMERIC(8, 4),
    total_pnl                       NUMERIC(14, 4),
    expectancy                      NUMERIC(8, 4),
    deflated_sharpe_ratio           NUMERIC(8, 4),
    probability_backtest_overfit    NUMERIC(6, 4),
    gt_score                        NUMERIC(10, 4),
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes                           TEXT
);

CREATE INDEX IF NOT EXISTS idx_strategy_trials_strategy ON strategy_trials(strategy_id);
CREATE INDEX IF NOT EXISTS idx_strategy_trials_created  ON strategy_trials(created_at DESC);

COMMENT ON TABLE strategy_trials IS
  'Every backtested parameter configuration tested per strategy, not just promoted ones. ON DELETE RESTRICT on strategy_id means a strategy with trial history cannot be hard-deleted out from under it — archive via strategies.archived_at instead.';


-- ────────────────────────────────────────────────────────────
-- VALIDATION_RUNS
-- Added 2026-06-21 (future-proofing migration). Generic results
-- table for walk-forward optimization, CPCV, Monte Carlo, and
-- synthetic stress tests. One row per run/fold.
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS validation_runs (
    id                              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id                     UUID NOT NULL REFERENCES strategies(id) ON DELETE RESTRICT,
    trial_id                        UUID REFERENCES strategy_trials(id) ON DELETE SET NULL,
    method                          VARCHAR(50) NOT NULL,
    is_synthetic                    BOOLEAN NOT NULL DEFAULT FALSE,
    fold_number                     INTEGER,
    in_sample_start                 TIMESTAMPTZ,
    in_sample_end                   TIMESTAMPTZ,
    out_sample_start                TIMESTAMPTZ,
    out_sample_end                  TIMESTAMPTZ,
    execution_cost_bps              NUMERIC(8, 4),
    slippage_model                  VARCHAR(50),
    sharpe_ratio                    NUMERIC(8, 4),
    sortino_ratio                   NUMERIC(8, 4),
    max_drawdown                    NUMERIC(8, 4),
    win_rate                        NUMERIC(6, 4),
    profit_factor                   NUMERIC(8, 4),
    total_pnl                       NUMERIC(14, 4),
    deflated_sharpe_ratio           NUMERIC(8, 4),
    probability_backtest_overfit    NUMERIC(6, 4),
    passed                          BOOLEAN,
    raw_results                     JSONB,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes                           TEXT
);

CREATE INDEX IF NOT EXISTS idx_validation_runs_strategy ON validation_runs(strategy_id);
CREATE INDEX IF NOT EXISTS idx_validation_runs_trial    ON validation_runs(trial_id);
CREATE INDEX IF NOT EXISTS idx_validation_runs_method   ON validation_runs(method);
CREATE INDEX IF NOT EXISTS idx_validation_runs_created  ON validation_runs(created_at DESC);

COMMENT ON TABLE validation_runs IS
  'Results table for WFO/CPCV/Monte Carlo/synthetic stress tests. is_synthetic distinguishes real-market-data runs from simulated ones. execution_cost_bps and slippage_model record the cost assumptions behind each result, since changing those assumptions changes the answer.';


-- ────────────────────────────────────────────────────────────
-- STRATEGY_LIFECYCLE_HISTORY
-- Added 2026-06-21 (future-proofing migration). Append-only log
-- of every lifecycle_state transition a strategy goes through,
-- with the reason and (when applicable) which trial or
-- validation run triggered it.
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS strategy_lifecycle_history (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id         UUID NOT NULL REFERENCES strategies(id) ON DELETE RESTRICT,
    from_state          VARCHAR(20),
    to_state            VARCHAR(20) NOT NULL,
    reason              VARCHAR(255),
    trial_id            UUID REFERENCES strategy_trials(id) ON DELETE SET NULL,
    validation_run_id   UUID REFERENCES validation_runs(id) ON DELETE SET NULL,
    transitioned_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes               TEXT
);

CREATE INDEX IF NOT EXISTS idx_lifecycle_history_strategy ON strategy_lifecycle_history(strategy_id);
CREATE INDEX IF NOT EXISTS idx_lifecycle_history_time     ON strategy_lifecycle_history(transitioned_at DESC);

COMMENT ON TABLE strategy_lifecycle_history IS
  'Append-only transition log. Lets a strategy fall off the live ranking without losing its history — the row in strategies changes state, but every state it ever held stays here.';


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
--     live; only the two legacy tables do). The three new tables
--     added 2026-06-21 also have none yet.
--   - Foreign keys on the original events/trades/performance
--     columns (strategy_id, entry_event_id, exit_event_id) still
--     use the Postgres default NO ACTION on delete, not
--     CASCADE/SET NULL. Only the three new tables added
--     2026-06-21 (strategy_trials, validation_runs,
--     strategy_lifecycle_history) have deliberate ON DELETE
--     RESTRICT / SET NULL behavior — confirmed live via \d.
--   - RESOLVED 2026-06-21: events and trades now have secondary
--     indexes (idx_events_strategy, idx_events_received_at,
--     idx_trades_strategy, idx_trades_status, idx_trades_entry_at)
--     — confirmed live. Previously every lookup against those
--     tables was a full table scan.
-- ============================================================
