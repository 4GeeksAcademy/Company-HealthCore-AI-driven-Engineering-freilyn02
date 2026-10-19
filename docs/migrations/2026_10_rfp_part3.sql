-- Milestone 9 Part 3: statuses + approval tables.
-- Run ONCE in the Supabase SQL editor (if the API creates tables with
-- SQLModel.metadata.create_all, the three NEW tables are created automatically, but the
-- CHECK constraint of the EXISTING rfp_tickets table must still be replaced).

ALTER TABLE rfp_tickets DROP CONSTRAINT IF EXISTS ck_rfp_tickets_status;
ALTER TABLE rfp_tickets ADD CONSTRAINT ck_rfp_tickets_status CHECK (
  status IN ('analyzing', 'discarded', 'intake_complete',
             'drafting', 'under_evaluation', 'needs_human_review',
             'waiting_for_approval', 'done')
);

CREATE TABLE IF NOT EXISTS rfp_approvals (
  id               SERIAL PRIMARY KEY,
  ticket_id        INTEGER NOT NULL REFERENCES rfp_tickets(id),
  department       VARCHAR(64) NOT NULL,
  approval_status  VARCHAR(32) NOT NULL DEFAULT 'pending',
  approver         VARCHAR(128),
  approved_at      TIMESTAMPTZ,
  revision_count   INTEGER NOT NULL DEFAULT 0,
  requested_changes TEXT,
  structured       JSON,
  contains_phi     BOOLEAN NOT NULL DEFAULT FALSE,
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_rfp_approvals_ticket_dept UNIQUE (ticket_id, department),
  CONSTRAINT ck_rfp_approvals_status CHECK (
    approval_status IN ('pending', 'approved', 'rejected', 'changes_requested'))
);
CREATE INDEX IF NOT EXISTS ix_rfp_approvals_ticket_id ON rfp_approvals(ticket_id);

CREATE TABLE IF NOT EXISTS rfp_trace_events (
  id          SERIAL PRIMARY KEY,
  ticket_id   INTEGER NOT NULL REFERENCES rfp_tickets(id),
  ts          VARCHAR(32) NOT NULL,
  agent       VARCHAR(128) NOT NULL,
  department  VARCHAR(64),
  input_ref   VARCHAR(512) NOT NULL,
  output_ref  VARCHAR(512) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rfp_trace_ticket ON rfp_trace_events(ticket_id);

CREATE TABLE IF NOT EXISTS rfp_final_documents (
  id            SERIAL PRIMARY KEY,
  ticket_id     INTEGER NOT NULL UNIQUE REFERENCES rfp_tickets(id),
  content_md    TEXT NOT NULL,
  path          VARCHAR(512),
  document      JSON,
  generated_at  VARCHAR(32) NOT NULL
);
