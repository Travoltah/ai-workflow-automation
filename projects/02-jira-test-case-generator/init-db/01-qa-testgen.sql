-- Runs once, the first time the Postgres container starts with an empty volume.
-- Creates a separate database for the test library so it never mixes with n8n's own tables.
-- To add it to an existing Postgres (for example project 01's stack), run:
--   docker compose exec -T postgres psql -U n8n -d n8n < init-db/01-qa-testgen.sql

CREATE DATABASE qa_testgen;
\connect qa_testgen

-- One row per generation run (one story, one call to Claude).
CREATE TABLE IF NOT EXISTS generation_runs (
  id                   BIGSERIAL PRIMARY KEY,
  issue_key            TEXT,                         -- NULL when the story was typed into the form or API
  story_summary        TEXT,
  channel              TEXT        NOT NULL,         -- form | api | schedule
  status               TEXT        NOT NULL,         -- ok | needs_clarification | not_a_story | error
  model                TEXT        NOT NULL,
  criteria_count       INT         NOT NULL DEFAULT 0,
  test_count           INT         NOT NULL DEFAULT 0,
  coverage_pct         NUMERIC(5,1),
  quality_passed       BOOLEAN     NOT NULL,
  quality_issues       JSONB       NOT NULL DEFAULT '[]',
  acceptance_criteria  JSONB       NOT NULL DEFAULT '[]',
  input_tokens         INT,
  output_tokens        INT,
  latency_ms           INT,
  review_status        TEXT        NOT NULL DEFAULT 'pending' CHECK (review_status IN ('pending', 'approved', 'rejected')),
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS generation_runs_issue_idx ON generation_runs (issue_key, created_at DESC);

-- One row per generated test case: the test library.
CREATE TABLE IF NOT EXISTS test_cases (
  id                    BIGSERIAL PRIMARY KEY,
  run_id                BIGINT      NOT NULL REFERENCES generation_runs (id) ON DELETE CASCADE,
  test_id               TEXT        NOT NULL,        -- TC-01, TC-02, ...
  title                 TEXT        NOT NULL,
  test_type             TEXT        NOT NULL,
  priority              TEXT        NOT NULL,
  covers                TEXT[]      NOT NULL,
  preconditions         TEXT,
  test_data             TEXT,
  steps                 JSONB       NOT NULL,
  expected_result       TEXT        NOT NULL,
  automation_candidate  BOOLEAN     NOT NULL,
  UNIQUE (run_id, test_id)
);

-- Latest run per Jira story (or every run for stories that didn't come from Jira).
CREATE OR REPLACE VIEW latest_runs AS
SELECT DISTINCT ON (coalesce(issue_key, id::text)) *
FROM generation_runs
ORDER BY coalesce(issue_key, id::text), created_at DESC;

-- Requirement-to-test traceability matrix, from the latest run of each story.
CREATE OR REPLACE VIEW traceability_matrix AS
SELECT r.issue_key,
       r.story_summary,
       ac ->> 'id'                                   AS criterion_id,
       ac ->> 'text'                                 AS criterion,
       ac ->> 'source'                               AS criterion_source,
       count(tc.id)                                  AS test_count,
       string_agg(tc.test_id, ', ' ORDER BY tc.test_id) AS covered_by
FROM latest_runs r
CROSS JOIN LATERAL jsonb_array_elements(r.acceptance_criteria) AS ac
LEFT JOIN test_cases tc ON tc.run_id = r.id AND (ac ->> 'id') = ANY (tc.covers)
GROUP BY r.id, r.issue_key, r.story_summary, ac;

-- Quality and cost of the generator over time: one row per day and model.
CREATE OR REPLACE VIEW generation_quality AS
SELECT date_trunc('day', created_at)::date                         AS day,
       model,
       count(*)                                                    AS runs,
       round(100.0 * avg(quality_passed::int), 1)                  AS quality_pass_pct,
       round(avg(coverage_pct) FILTER (WHERE status = 'ok'), 1)    AS avg_coverage_pct,
       round(avg(test_count) FILTER (WHERE status = 'ok'), 1)      AS avg_tests_per_story,
       count(*) FILTER (WHERE status = 'needs_clarification')      AS clarifications,
       round(avg(latency_ms) / 1000.0, 1)                          AS avg_latency_s,
       sum(input_tokens)                                           AS input_tokens,
       sum(output_tokens)                                          AS output_tokens
FROM generation_runs
GROUP BY 1, 2
ORDER BY 1 DESC, 2;
