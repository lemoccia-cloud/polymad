-- Migration 001: Initial schema
-- Documents the baseline schema already present in production.
-- Running this migration on a fresh database recreates the full initial state.

CREATE TABLE IF NOT EXISTS users (
    wallet_address TEXT PRIMARY KEY,
    plan           TEXT    NOT NULL DEFAULT 'free',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    stripe_customer_id TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS alert_configs (
    wallet_address TEXT PRIMARY KEY REFERENCES users(wallet_address) ON DELETE CASCADE,
    edge_threshold FLOAT   NOT NULL DEFAULT 0.05,
    categories     TEXT[]  NOT NULL DEFAULT ARRAY['weather'],
    notify_email   TEXT,
    telegram_chat_id TEXT,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index already present in production
CREATE INDEX IF NOT EXISTS idx_users_stripe ON users (stripe_customer_id);
