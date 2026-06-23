-- ============================================================
-- Apex Engine — Future-Proofing Migration (2026-06-21)
-- Task: pre-launch placeholder columns, requested before any
-- real strategy/trade/event data accumulates. Broad scope per
-- explicit direction: "account for anyone trading anything
-- across all platforms." Safe to run multiple times (every
-- statement is idempotent via IF NOT EXISTS / guarded ALTER).
--
-- Tables currently hold ~0 rows (1 strategy, 0 trades/events),
-- so every ALTER here is instant — no locking concern.
-- ============================================================

-- ────────────────────────────────────────────────────────────
-- STRATEGIES
-- ────────────────────────────────────────────────────────────
ALTER TABLE strategies ADD COLUMN IF NOT EXISTS owner_id    UUID;
ALTER TABLE strategies ADD COLUMN IF NOT EXISTS updated_at  TIMESTAMPTZ DEFAULT NOW();

COMMENT ON COLUMN strategies.owner_id IS
  'Future multi-tenant owner/tenant identifier. NULL = system-owned (current solo-trader phase). Not yet enforced by any FK — user/billing DB does not exist yet.';

-- ────────────────────────────────────────────────────────────
-- EVENTS
-- ────────────────────────────────────────────────────────────
ALTER TABLE events ADD COLUMN IF NOT EXISTS broker             VARCHAR(50) DEFAULT 'alpaca';
ALTER TABLE events ADD COLUMN IF NOT EXISTS currency           VARCHAR(10) DEFAULT 'USD';
ALTER TABLE events ADD COLUMN IF NOT EXISTS external_signal_id VARCHAR(255);
ALTER TABLE events ADD COLUMN IF NOT EXISTS source_signal_at   TIMESTAMPTZ;

COMMENT ON COLUMN events.external_signal_id IS
  'Placeholder for a future idempotency/dedupe key (e.g. webhook delivery ID). Nullable, no UNIQUE constraint yet — decide the real key once actual ingestion payload structure is confirmed.';

COMMENT ON COLUMN events.source_signal_at IS
  'Timestamp the source/strategy claims the signal occurred, extracted from raw_payload if present. Distinct from received_at (our system arrival time) — lets us measure source-to-ingestion latency and detect out-of-order or delayed delivery without guessing. Nullable: not every source payload will carry one.';

ALTER TABLE events ALTER COLUMN ticker        TYPE VARCHAR(32);
ALTER TABLE events ALTER COLUMN signal_price   TYPE NUMERIC(18, 8);
ALTER TABLE events ALTER COLUMN quantity       TYPE NUMERIC(18, 8);

CREATE INDEX IF NOT EXISTS idx_events_strategy     ON events(strategy_id);
CREATE INDEX IF NOT EXISTS idx_events_received_at  ON events(received_at DESC);

-- ────────────────────────────────────────────────────────────
-- TRADES
-- ────────────────────────────────────────────────────────────
ALTER TABLE trades ADD COLUMN IF NOT EXISTS updated_at  TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE trades ADD COLUMN IF NOT EXISTS broker      VARCHAR(50) DEFAULT 'alpaca';
ALTER TABLE trades ADD COLUMN IF NOT EXISTS currency    VARCHAR(10) DEFAULT 'USD';

ALTER TABLE trades ALTER COLUMN ticker       TYPE VARCHAR(32);
ALTER TABLE trades ALTER COLUMN entry_price  TYPE NUMERIC(18, 8);
ALTER TABLE trades ALTER COLUMN exit_price   TYPE NUMERIC(18, 8);
ALTER TABLE trades ALTER COLUMN quantity     TYPE NUMERIC(18, 8);
ALTER TABLE trades ALTER COLUMN pnl          TYPE NUMERIC(18, 8);

CREATE INDEX IF NOT EXISTS idx_trades_strategy  ON trades(strategy_id);
CREATE INDEX IF NOT EXISTS idx_trades_status    ON trades(status);
CREATE INDEX IF NOT EXISTS idx_trades_entry_at  ON trades(entry_at DESC);

-- ────────────────────────────────────────────────────────────
-- PERFORMANCE
-- ────────────────────────────────────────────────────────────
ALTER TABLE performance ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

ALTER TABLE performance ALTER COLUMN total_pnl  TYPE NUMERIC(18, 8);
ALTER TABLE performance ALTER COLUMN avg_win    TYPE NUMERIC(18, 8);
ALTER TABLE performance ALTER COLUMN avg_loss   TYPE NUMERIC(18, 8);

-- ────────────────────────────────────────────────────────────
-- DEAD LETTERS
-- ────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_dead_letters_unresolved
  ON dead_letters(received_at DESC) WHERE resolved = FALSE;

-- ────────────────────────────────────────────────────────────
-- STRATEGY_TRIALS
-- Every backtested parameter configuration tested per strategy,
-- not just the ones that got promoted. Feeds DSR/PBO/GT-Score —
-- those calculations need the full search space, not just the
-- survivorship-biased winners.
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
-- Generic results table for walk-forward optimization, CPCV,
-- Monte Carlo, and synthetic stress tests. One row per run/fold.
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
-- Append-only log of every lifecycle_state transition a strategy
-- goes through, with the reason and (when applicable) which
-- trial or validation run triggered it.
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

-- ============================================================
-- End of migration. After this runs cleanly, verify with \d on
-- each table, then db_schema.sql gets rewritten to match the
-- new confirmed-live state (not before).
-- ============================================================
