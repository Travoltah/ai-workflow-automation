-- NODE: "Save to test library"  (Postgres node, operation: Execute Query)
-- Query Parameters: {{ [ JSON.stringify($json.record) ] }}
-- Saves the run and all its test cases in one statement, from a single JSON parameter
-- (one parameter avoids any problems with commas or quotes inside the test text).
WITH p AS (SELECT $1::jsonb AS j),
run AS (
  INSERT INTO generation_runs (issue_key, story_summary, channel, status, model, criteria_count, test_count,
                               coverage_pct, quality_passed, quality_issues, acceptance_criteria,
                               input_tokens, output_tokens, latency_ms)
  SELECT j->>'issueKey', j->>'summary', j->>'channel', j->>'status', j->>'model',
         (j->>'criteriaCount')::int, (j->>'testCount')::int, (j->>'coveragePct')::numeric,
         (j->>'qualityPassed')::boolean, j->'qualityIssues', j->'acceptanceCriteria',
         (j->>'inputTokens')::int, (j->>'outputTokens')::int, (j->>'latencyMs')::int
  FROM p
  RETURNING id
),
saved AS (
  INSERT INTO test_cases (run_id, test_id, title, test_type, priority, covers, preconditions, test_data,
                          steps, expected_result, automation_candidate)
  SELECT run.id, t->>'id', t->>'title', t->>'type', t->>'priority',
         ARRAY(SELECT jsonb_array_elements_text(t->'covers')),
         t->>'preconditions', t->>'testData', t->'steps', t->>'expectedResult',
         (t->>'automationCandidate')::boolean
  FROM run, p, jsonb_array_elements(p.j->'testCases') AS t
  RETURNING 1
)
SELECT (SELECT id FROM run) AS run_id, (SELECT count(*) FROM saved) AS test_cases_saved;
