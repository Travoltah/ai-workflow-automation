-- Runs once, the first time the Postgres container starts with an empty volume.
-- Creates a separate database for chatbot analytics so it never mixes with n8n's own tables.

CREATE DATABASE faq_analytics;
\connect faq_analytics

-- Questions the chatbot could not answer from the knowledge base.
-- This is the FAQ owner's to-do list: the most frequent gaps are the next FAQ entries to write.
CREATE TABLE IF NOT EXISTS faq_gaps (
  id          BIGSERIAL PRIMARY KEY,
  question    TEXT        NOT NULL,
  session_id  TEXT,
  status      TEXT        NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'added_to_faq', 'out_of_scope')),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS faq_gaps_created_at_idx ON faq_gaps (created_at DESC);

-- Ready-made report: most common unanswered questions in the last 30 days.
CREATE OR REPLACE VIEW faq_gap_report AS
SELECT lower(trim(question)) AS question,
       count(*)              AS times_asked,
       max(created_at)       AS last_asked
FROM faq_gaps
WHERE status = 'open' AND created_at > now() - interval '30 days'
GROUP BY 1
ORDER BY times_asked DESC, last_asked DESC;
