-- Transaction Ledger schema. Apply it to both the app and the test database:
--   psql -h "$DB_HOST" -d "$DB_NAME" -f db/schema.sql
--   psql -h "$DB_HOST" -d "$TEST_DB_NAME" -f db/schema.sql
-- Safe to re-run: existing tables are left as they are. A database created before
-- the length checks on transactions needs them added by hand:
--   ALTER TABLE transactions ADD CONSTRAINT transactions_description_length CHECK (length(description) <= 255);
--   ALTER TABLE transactions ADD CONSTRAINT transactions_reference_id_length CHECK (length(reference_id) <= 100);
-- and, for the non-blank check on reference_id:
--   ALTER TABLE transactions ADD CONSTRAINT transactions_reference_id_not_blank CHECK (length(btrim(reference_id)) > 0);
-- and, for transfers:
--   ALTER TABLE transactions ADD COLUMN IF NOT EXISTS transfer_id UUID;

CREATE TABLE IF NOT EXISTS accounts (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL CHECK (length(btrim(name)) > 0)
                CONSTRAINT accounts_name_length CHECK (length(name) <= 100),
    balance     NUMERIC(18, 2) NOT NULL DEFAULT 0 CHECK (balance >= 0),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS transactions (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id   UUID NOT NULL
                 CONSTRAINT transactions_account_id_fkey REFERENCES accounts (id),
    type         TEXT NOT NULL CHECK (type IN ('credit', 'debit')),
    amount       NUMERIC(18, 2) NOT NULL CHECK (amount > 0),
    description  TEXT NOT NULL DEFAULT ''
                 CONSTRAINT transactions_description_length CHECK (length(description) <= 255),
    reference_id TEXT NOT NULL
                 CONSTRAINT transactions_reference_id_length CHECK (length(reference_id) <= 100),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Set on both rows of a transfer (same value); NULL for an ordinary transaction.
    transfer_id  UUID,
    CONSTRAINT transactions_reference_id_not_blank CHECK (length(btrim(reference_id)) > 0),
    CONSTRAINT transactions_account_id_reference_id_key UNIQUE (account_id, reference_id)
);

-- Serves the history query: one account's rows, latest first, with the id tie-breaker.
CREATE INDEX IF NOT EXISTS transactions_account_history_idx
    ON transactions (account_id, created_at DESC, id DESC);
