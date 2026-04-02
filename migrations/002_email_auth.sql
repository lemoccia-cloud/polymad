-- Migration 002: Email authentication support
-- Adds columns required for Supabase Auth (email/password) users.
-- Fully additive — no existing data is changed.

ALTER TABLE users ADD COLUMN IF NOT EXISTS email             TEXT UNIQUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_provider     TEXT NOT NULL DEFAULT 'wallet';
ALTER TABLE users ADD COLUMN IF NOT EXISTS display_name      TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS supabase_user_id  TEXT UNIQUE;

-- Fast lookup for email users during login
CREATE INDEX IF NOT EXISTS idx_users_email       ON users (email);
CREATE INDEX IF NOT EXISTS idx_users_supabase_id ON users (supabase_user_id);

-- Constrain auth_provider to known values
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'users_auth_provider_check'
    ) THEN
        ALTER TABLE users ADD CONSTRAINT users_auth_provider_check
            CHECK (auth_provider IN ('wallet', 'email'));
    END IF;
END$$;
