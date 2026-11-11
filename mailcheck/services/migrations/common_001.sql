CREATE TABLE outbox (
 event_id UUID PRIMARY KEY,
 routing_key TEXT NOT NULL CHECK (length(routing_key) BETWEEN 1 AND 160),
 payload JSONB NOT NULL CHECK (octet_length(payload::text) <= 65536),
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 published_at TIMESTAMPTZ,
 attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0)
);
CREATE INDEX outbox_pending ON outbox(created_at) WHERE published_at IS NULL;
CREATE TABLE processed_events (
 consumer TEXT NOT NULL,
 event_id UUID NOT NULL,
 processed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(consumer,event_id)
);
CREATE TABLE durable_jobs (
 job_id UUID PRIMARY KEY,
 workspace_id TEXT NOT NULL,
 kind TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('pending','running','completed','failed','uncertain','cancelled')),
 revision BIGINT NOT NULL DEFAULT 0,
 lease_until TIMESTAMPTZ,
 attempts INTEGER NOT NULL DEFAULT 0,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
