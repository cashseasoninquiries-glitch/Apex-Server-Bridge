-- Enable the UUID extension for cryptographic tracking keys
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- TABLE 1: Vectorized Strategy Signals (The Analytical Ledger)
CREATE TABLE IF NOT EXISTS strategy_signals (
    timestamp TIMESTAMPTZ NOT NULL,
    strategy_id VARCHAR(64) NOT NULL,
    symbol VARCHAR(16) NOT NULL,
    signal_value SMALLINT NOT NULL CHECK (signal_value IN (-1, 0, 1)), -- 1=Long, -1=Short, 0=Flat
    stop_loss NUMERIC(18, 8),
    take_profit NUMERIC(18, 8),
    metadata JSONB, -- For tracking dynamic technical indicators at the millisecond of entry
    
    -- THE FORTRESS KEY: Mathematically blocks duplicate writes across high concurrency
    PRIMARY KEY (timestamp, strategy_id, symbol)
);

-- CREATE INDEXES FOR ULTRA-FAST TIME-SERIES QUERIES
CREATE INDEX IF NOT EXISTS idx_signals_time_strat ON strategy_signals (strategy_id, timestamp DESC);

-- TABLE 2: Execution Ledger (The Physical Order Ledger)
CREATE TABLE IF NOT EXISTS execution_ledger (
    execution_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    timestamp TIMESTAMPTZ NOT NULL,
    strategy_id VARCHAR(64) NOT NULL,
    symbol VARCHAR(16) NOT NULL,
    direction VARCHAR(10) NOT NULL CHECK (direction IN ('BUY', 'SELL', 'LIQUIDATE')),
    execution_price NUMERIC(18, 8) NOT NULL,
    quantity NUMERIC(18, 8) NOT NULL,
    run_id UUID NOT NULL, -- Ties back to the exact Docker run sequence
    is_simulated BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_execution_time ON execution_ledger (timestamp DESC);
