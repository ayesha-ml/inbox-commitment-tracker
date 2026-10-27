CREATE TABLE IF NOT EXISTS users (
  user_id      TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  created_at   TEXT NOT NULL
);

-- Simulated clock so cycles can be advanced manually
CREATE TABLE IF NOT EXISTS clock (
  user_id   TEXT PRIMARY KEY REFERENCES users(user_id),
  today     TEXT NOT NULL
);

-- Every email ever processed (dedup + evidence source)
CREATE TABLE IF NOT EXISTS messages (
  message_id   TEXT NOT NULL,          -- Message-ID header or fixture id
  user_id      TEXT NOT NULL REFERENCES users(user_id),
  thread_id    TEXT,
  sender       TEXT,
  subject      TEXT,
  body         TEXT,
  body_hash    TEXT NOT NULL,          -- SHA-256 of normalised body
  source       TEXT NOT NULL,          -- 'imap' or 'fixture_export'
  cycle_id     INTEGER,
  received_at  TEXT,
  ingested_at  TEXT NOT NULL,
  llm_label    TEXT,                   -- NEW/REVISION/DUPLICATE/FULFILLED/UNCLEAR
  PRIMARY KEY (user_id, message_id),
  UNIQUE (user_id, body_hash)          -- same content twice = duplicate
);

-- One row per commitment (the stable identity)
CREATE TABLE IF NOT EXISTS commitments (
  commitment_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id         TEXT NOT NULL REFERENCES users(user_id),
  thread_id       TEXT,
  owner           TEXT NOT NULL,       -- who promised
  counterparty    TEXT,                -- who it was promised to
  description     TEXT NOT NULL,
  status          TEXT NOT NULL CHECK (status IN
                    ('OPEN','NEEDS_REVIEW','FULFILLED','CANCELLED')),
  created_at      TEXT NOT NULL
);

-- Version history: current vs superseded
CREATE TABLE IF NOT EXISTS commitment_versions (
  commitment_id     INTEGER NOT NULL REFERENCES commitments(commitment_id),
  version           INTEGER NOT NULL,
  deadline          TEXT,              -- ISO date, NULL if unclear
  is_current        INTEGER NOT NULL DEFAULT 1,
  source_message_id TEXT NOT NULL,
  evidence_quote    TEXT,              -- exact snippet that justifies it
  recorded_at       TEXT NOT NULL,
  superseded_at     TEXT,
  PRIMARY KEY (commitment_id, version)
);

-- Reminders: draft, approval, and send tracked separately
CREATE TABLE IF NOT EXISTS reminders (
  reminder_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id          TEXT NOT NULL REFERENCES users(user_id),
  commitment_id    INTEGER NOT NULL REFERENCES commitments(commitment_id),
  deadline_version INTEGER NOT NULL,
  reminder_n       INTEGER NOT NULL,   -- 1st, 2nd... (limit enforced in code)
  recipient        TEXT NOT NULL,
  draft_body       TEXT NOT NULL,
  draft_state      TEXT NOT NULL DEFAULT 'UNSENT_DRAFT',
  approval_state   TEXT NOT NULL DEFAULT 'PENDING'
                     CHECK (approval_state IN ('PENDING','APPROVED','REJECTED')),
  send_state       TEXT NOT NULL DEFAULT 'NOT_SENT'
                     CHECK (send_state IN ('NOT_SENT','SENT','FAILED')),
  send_error       TEXT,
  idempotency_key  TEXT NOT NULL UNIQUE, -- user+commitment+version+n
  created_at       TEXT NOT NULL,
  updated_at       TEXT NOT NULL
);

-- Everything the agent does, for auditing and the report
CREATE TABLE IF NOT EXISTS action_log (
  log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     TEXT NOT NULL,
  cycle_id    INTEGER,
  ts          TEXT NOT NULL,
  kind        TEXT NOT NULL,           -- TOOL_CALL / MEMORY_READ / MEMORY_WRITE / LLM_CALL / ERROR
  tool        TEXT,
  input_json  TEXT,
  output_json TEXT,
  outcome     TEXT,                    -- ok / blocked / error
  latency_ms  INTEGER,
  tokens_in   INTEGER,
  tokens_out  INTEGER
);

-- Working state, bounded, resumable after interruption
CREATE TABLE IF NOT EXISTS checkpoints (
  user_id    TEXT NOT NULL,
  cycle_id   INTEGER NOT NULL,
  state_json TEXT NOT NULL,            -- step, pending questions, plan
  updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, cycle_id)
);

CREATE INDEX IF NOT EXISTS idx_commit_user ON commitments(user_id, status);
CREATE INDEX IF NOT EXISTS idx_log_user ON action_log(user_id, ts);