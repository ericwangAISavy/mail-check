CREATE TABLE event_heads (
 workspace_id TEXT PRIMARY KEY CHECK (length(workspace_id) BETWEEN 1 AND 64),
 position BIGINT NOT NULL DEFAULT 0 CHECK (position >= 0),
 retained_after BIGINT NOT NULL DEFAULT 0 CHECK(retained_after >= 0 AND retained_after <= position)
);
CREATE TABLE client_events (
 workspace_id TEXT NOT NULL REFERENCES event_heads(workspace_id),
 position BIGINT NOT NULL CHECK(position > 0),
 event_id UUID NOT NULL,
 account_id TEXT,
 kind TEXT NOT NULL,
 payload JSONB NOT NULL CHECK(octet_length(payload::text) <= 16384),
 fingerprint TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(workspace_id,position),
 UNIQUE(workspace_id,event_id)
);
CREATE INDEX client_events_retention ON client_events(created_at);
