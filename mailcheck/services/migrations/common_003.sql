ALTER TABLE outbox ADD COLUMN lease_token UUID;
ALTER TABLE outbox ADD COLUMN lease_until TIMESTAMPTZ;
ALTER TABLE outbox ADD COLUMN next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE INDEX outbox_due ON outbox(next_attempt_at) WHERE published_at IS NULL;
