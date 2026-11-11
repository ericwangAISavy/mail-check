-- Dedupe identity outlives the short-lived client replay journal.
CREATE TABLE journal_event_receipts (
 workspace_id TEXT NOT NULL REFERENCES event_heads(workspace_id),
 event_id UUID NOT NULL,
 position BIGINT NOT NULL,
 fingerprint TEXT NOT NULL,
 PRIMARY KEY(workspace_id,event_id)
);
INSERT INTO journal_event_receipts(workspace_id,event_id,position,fingerprint)
 SELECT workspace_id,event_id,position,fingerprint FROM client_events;
