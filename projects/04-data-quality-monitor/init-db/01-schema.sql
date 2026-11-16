-- AI Data Quality Monitor: database schema.
-- wallet.* = the business data being monitored (Contoso Pay, a fictional mobile wallet).
-- dq.*     = the monitor: rules, runs, results, incidents, and the functions n8n calls.
-- Runs automatically when the Postgres container is first created (docker-entrypoint-initdb.d).

\connect contoso_dq

CREATE SCHEMA IF NOT EXISTS wallet;
CREATE SCHEMA IF NOT EXISTS dq;

-- ───────────────────────────── business data ─────────────────────────────
-- No foreign keys on purpose: data arrives from several source systems, as in most
-- warehouses, and integrity is checked by the monitor instead of enforced on load.
CREATE TABLE IF NOT EXISTS wallet.customers (
  customer_id  int PRIMARY KEY,
  full_name    text NOT NULL,
  email        text,
  phone        text,
  kyc_status   text,
  country      text,
  created_at   timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS wallet.wallets (
  wallet_id    int PRIMARY KEY,
  customer_id  int,
  currency     text,
  status       text,
  balance      numeric(14,2),
  opened_at    timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS wallet.transactions (
  txn_id        bigint PRIMARY KEY,
  wallet_id     int,
  txn_type      text,          -- deposit | withdrawal | p2p_send | p2p_receive
  amount        numeric(14,2),
  fee           numeric(14,2),
  status        text,          -- completed | failed | pending
  external_ref  text,          -- the reference from the payment switch; must be unique
  created_at    timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS transactions_wallet_time ON wallet.transactions (wallet_id, created_at);
CREATE INDEX IF NOT EXISTS transactions_ref ON wallet.transactions (external_ref);

CREATE TABLE IF NOT EXISTS wallet.daily_ledger (
  ledger_date      date,
  wallet_id        int,
  opening_balance  numeric(14,2),
  total_credits    numeric(14,2),
  total_debits     numeric(14,2),
  closing_balance  numeric(14,2),
  PRIMARY KEY (ledger_date, wallet_id)
);

CREATE TABLE IF NOT EXISTS wallet.feed_loads (
  feed_name       text PRIMARY KEY,
  source_system   text,
  last_loaded_at  timestamptz,
  rows_loaded     int,
  sla_hours       int
);

-- ───────────────────────────── the monitor ─────────────────────────────
CREATE TABLE IF NOT EXISTS dq.rules (
  rule_code    text PRIMARY KEY,
  rule_name    text NOT NULL,
  dimension    text NOT NULL CHECK (dimension IN ('completeness','validity','uniqueness','integrity','consistency','timeliness','volume')),
  table_name   text NOT NULL,
  severity     text NOT NULL CHECK (severity IN ('critical','high','medium','low')),
  owner        text NOT NULL,
  description  text NOT NULL,
  -- A query that returns one row per violation with two columns: the record id, then a detail text.
  -- Column names don't matter; run_checks renames them by position.
  check_sql    text NOT NULL,
  active       boolean NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS dq.runs (
  run_id         serial PRIMARY KEY,
  trigger        text NOT NULL,
  started_at     timestamptz NOT NULL DEFAULT now(),
  finished_at    timestamptz,
  checks_run     int,
  checks_failed  int,
  checks_errored int,
  model          text,
  input_tokens   int DEFAULT 0,
  output_tokens  int DEFAULT 0,
  cost_usd       numeric(8,4) DEFAULT 0,
  status         text NOT NULL DEFAULT 'running'
);

CREATE TABLE IF NOT EXISTS dq.results (
  run_id         int REFERENCES dq.runs(run_id) ON DELETE CASCADE,
  rule_code      text REFERENCES dq.rules(rule_code),
  status         text NOT NULL CHECK (status IN ('pass','fail','error')),
  failing_count  int NOT NULL DEFAULT 0,
  sample_rows    jsonb NOT NULL DEFAULT '[]',
  record_ids     text[] NOT NULL DEFAULT '{}',   -- up to 1,000 failing record ids, for audit and evaluation
  error_message  text,
  duration_ms    int,
  PRIMARY KEY (run_id, rule_code)
);

CREATE TABLE IF NOT EXISTS dq.incidents (
  incident_id     serial PRIMARY KEY,
  rule_code       text REFERENCES dq.rules(rule_code),
  status          text NOT NULL CHECK (status IN ('open','resolved')),
  opened_run      int REFERENCES dq.runs(run_id),
  last_seen_run   int REFERENCES dq.runs(run_id),
  resolved_run    int REFERENCES dq.runs(run_id),
  first_count     int,
  last_count      int,
  jira_key        text,
  explanation     jsonb,          -- Claude's explanation, after the code check
  explanation_ok  boolean,        -- false = the explanation failed the check and was not used
  opened_at       timestamptz NOT NULL DEFAULT now(),
  resolved_at     timestamptz
);
-- At most one open incident per rule: a repeat failure updates it instead of opening another.
CREATE UNIQUE INDEX IF NOT EXISTS one_open_incident_per_rule ON dq.incidents (rule_code) WHERE status = 'open';

-- ───────────────────────────── functions called by n8n ─────────────────────────────

-- Runs every active rule, stores the results, opens / updates / resolves incidents,
-- and returns what changed. Deterministic: no AI involved.
CREATE OR REPLACE FUNCTION dq.run_checks(p_trigger text, p_sample_size int DEFAULT 5)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE
  v_run     int;
  r         dq.rules%ROWTYPE;
  v_count   int;
  v_sample  jsonb;
  v_ids     text[];
  v_status  text;
  v_error   text;
  v_t0      timestamptz;
  v_actions jsonb := '[]';
  i         record;
BEGIN
  INSERT INTO dq.runs (trigger) VALUES (p_trigger) RETURNING run_id INTO v_run;

  FOR r IN SELECT * FROM dq.rules WHERE active ORDER BY rule_code LOOP
    v_t0 := clock_timestamp();
    v_error := NULL;
    BEGIN
      EXECUTE format(
        'SELECT count(*)::int,
                coalesce(jsonb_agg(to_jsonb(x) - ''rn'') FILTER (WHERE rn <= %s), ''[]''),
                coalesce(array_agg(x.record_id) FILTER (WHERE rn <= 1000), ''{}'')
           FROM (SELECT t.record_id::text AS record_id, t.detail::text AS detail,
                        row_number() OVER (ORDER BY t.record_id::text) AS rn
                   FROM (%s) AS t(record_id, detail)) x', p_sample_size, r.check_sql)
        INTO v_count, v_sample, v_ids;
      v_status := CASE WHEN v_count = 0 THEN 'pass' ELSE 'fail' END;
    EXCEPTION WHEN OTHERS THEN
      v_status := 'error'; v_error := SQLERRM; v_count := 0; v_sample := '[]'; v_ids := '{}';
    END;
    INSERT INTO dq.results (run_id, rule_code, status, failing_count, sample_rows, record_ids, error_message, duration_ms)
    VALUES (v_run, r.rule_code, v_status, v_count, v_sample, v_ids, v_error,
            (extract(epoch FROM clock_timestamp() - v_t0) * 1000)::int);
  END LOOP;

  -- New incidents: failing rules without an open incident.
  FOR i IN
    INSERT INTO dq.incidents (rule_code, status, opened_run, last_seen_run, first_count, last_count)
    SELECT res.rule_code, 'open', v_run, v_run, res.failing_count, res.failing_count
      FROM dq.results res
     WHERE res.run_id = v_run AND res.status = 'fail'
       AND NOT EXISTS (SELECT 1 FROM dq.incidents o WHERE o.rule_code = res.rule_code AND o.status = 'open')
    RETURNING incident_id, rule_code
  LOOP
    v_actions := v_actions || jsonb_build_object('action', 'new', 'incident_id', i.incident_id, 'rule_code', i.rule_code);
  END LOOP;

  -- Ongoing incidents: still failing. Remember the previous count before updating.
  FOR i IN
    WITH prev AS (
      SELECT o.incident_id, o.rule_code, o.last_count AS previous_count
        FROM dq.incidents o JOIN dq.results res ON res.rule_code = o.rule_code AND res.run_id = v_run
       WHERE o.status = 'open' AND o.opened_run <> v_run AND res.status = 'fail'
    )
    UPDATE dq.incidents o SET last_seen_run = v_run, last_count = res.failing_count
      FROM prev JOIN dq.results res ON res.rule_code = prev.rule_code AND res.run_id = v_run
     WHERE o.incident_id = prev.incident_id
    RETURNING o.incident_id, o.rule_code, prev.previous_count
  LOOP
    v_actions := v_actions || jsonb_build_object('action', 'ongoing', 'incident_id', i.incident_id,
                                                 'rule_code', i.rule_code, 'previous_count', i.previous_count);
  END LOOP;

  -- Resolved incidents: the rule passed this run. (An errored rule keeps its incident open.)
  FOR i IN
    UPDATE dq.incidents o SET status = 'resolved', resolved_run = v_run, resolved_at = now()
      FROM dq.results res
     WHERE res.rule_code = o.rule_code AND res.run_id = v_run AND res.status = 'pass' AND o.status = 'open'
    RETURNING o.incident_id, o.rule_code, o.last_count
  LOOP
    v_actions := v_actions || jsonb_build_object('action', 'resolved', 'incident_id', i.incident_id,
                                                 'rule_code', i.rule_code, 'previous_count', i.last_count);
  END LOOP;

  UPDATE dq.runs SET
    checks_run     = (SELECT count(*) FROM dq.results WHERE run_id = v_run),
    checks_failed  = (SELECT count(*) FROM dq.results WHERE run_id = v_run AND status = 'fail'),
    checks_errored = (SELECT count(*) FROM dq.results WHERE run_id = v_run AND status = 'error')
  WHERE run_id = v_run;

  -- Enrich every action with the rule and the evidence, so n8n needs no further queries.
  RETURN jsonb_build_object(
    'run_id', v_run,
    'checks_run',     (SELECT checks_run FROM dq.runs WHERE run_id = v_run),
    'checks_failed',  (SELECT checks_failed FROM dq.runs WHERE run_id = v_run),
    'checks_errored', (SELECT checks_errored FROM dq.runs WHERE run_id = v_run),
    'errors', (SELECT coalesce(jsonb_agg(jsonb_build_object('rule_code', rule_code, 'error', error_message)), '[]')
                 FROM dq.results WHERE run_id = v_run AND status = 'error'),
    'actions', (
      SELECT coalesce(jsonb_agg(a.value || jsonb_build_object(
               'rule_name', ru.rule_name, 'dimension', ru.dimension, 'table_name', ru.table_name,
               'severity', ru.severity, 'owner', ru.owner, 'description', ru.description, 'check_sql', ru.check_sql,
               'failing_count', res.failing_count, 'sample_rows', res.sample_rows, 'jira_key', inc.jira_key)
             ORDER BY a.value->>'action', a.value->>'rule_code'), '[]')
        FROM jsonb_array_elements(v_actions) a
        JOIN dq.rules ru ON ru.rule_code = a.value->>'rule_code'
        JOIN dq.results res ON res.rule_code = ru.rule_code AND res.run_id = v_run
        JOIN dq.incidents inc ON inc.incident_id = (a.value->>'incident_id')::int)
  );
END $$;

-- Stores the checked explanations: [{incident_id, explanation, explanation_ok}]
CREATE OR REPLACE FUNCTION dq.save_explanations(p jsonb) RETURNS int LANGUAGE sql AS $$
  WITH upd AS (
    UPDATE dq.incidents i SET explanation = e.value->'explanation', explanation_ok = (e.value->>'explanation_ok')::boolean
      FROM jsonb_array_elements(p) e
     WHERE i.incident_id = (e.value->>'incident_id')::int
    RETURNING 1)
  SELECT count(*)::int FROM upd;
$$;

-- Stores the Jira keys of new tickets: [{incident_id, jira_key}]
CREATE OR REPLACE FUNCTION dq.record_jira(p jsonb) RETURNS int LANGUAGE sql AS $$
  WITH upd AS (
    UPDATE dq.incidents i SET jira_key = e.value->>'jira_key'
      FROM jsonb_array_elements(p) e
     WHERE i.incident_id = (e.value->>'incident_id')::int AND coalesce(e.value->>'jira_key', '') <> ''
    RETURNING 1)
  SELECT count(*)::int FROM upd;
$$;

-- Closes the run with token usage and returns the summary the API and the report use.
CREATE OR REPLACE FUNCTION dq.finish_run(p_run int, p_usage jsonb) RETURNS jsonb LANGUAGE plpgsql AS $$
BEGIN
  UPDATE dq.runs SET finished_at = now(), status = 'finished',
         model = p_usage->>'model',
         input_tokens = coalesce((p_usage->>'input_tokens')::int, 0),
         output_tokens = coalesce((p_usage->>'output_tokens')::int, 0),
         cost_usd = coalesce((p_usage->>'cost_usd')::numeric, 0)
   WHERE run_id = p_run;
  RETURN dq.run_summary(p_run);
END $$;

CREATE OR REPLACE FUNCTION dq.run_summary(p_run int) RETURNS jsonb LANGUAGE sql STABLE AS $$
  SELECT jsonb_build_object(
    'run_id', r.run_id, 'trigger', r.trigger, 'started_at', r.started_at, 'finished_at', r.finished_at,
    'checks_run', r.checks_run, 'checks_failed', r.checks_failed, 'checks_errored', r.checks_errored,
    'pass_rate_pct', round(100.0 * (r.checks_run - r.checks_failed - r.checks_errored) / nullif(r.checks_run, 0), 1),
    'model', r.model, 'input_tokens', r.input_tokens, 'output_tokens', r.output_tokens, 'cost_usd', r.cost_usd,
    'failures', (
      SELECT coalesce(jsonb_agg(jsonb_build_object(
               'rule_code', res.rule_code, 'rule_name', ru.rule_name, 'dimension', ru.dimension, 'severity', ru.severity,
               'table_name', ru.table_name, 'failing_count', res.failing_count, 'record_ids', res.record_ids,
               'sample_rows', res.sample_rows, 'incident_id', inc.incident_id, 'jira_key', inc.jira_key,
               'opened_run', inc.opened_run, 'explanation', inc.explanation, 'explanation_ok', inc.explanation_ok)
             ORDER BY array_position(ARRAY['critical','high','medium','low'], ru.severity), res.rule_code), '[]')
        FROM dq.results res
        JOIN dq.rules ru USING (rule_code)
        -- the incident that was open during this run (so past runs keep their explanations)
        LEFT JOIN dq.incidents inc ON inc.rule_code = res.rule_code AND inc.opened_run <= r.run_id
             AND (inc.resolved_run IS NULL OR inc.resolved_run > r.run_id)
       WHERE res.run_id = r.run_id AND res.status = 'fail'),
    'errors', (SELECT coalesce(jsonb_agg(jsonb_build_object('rule_code', rule_code, 'error', error_message)), '[]')
                 FROM dq.results WHERE run_id = r.run_id AND status = 'error'),
    'resolved', (SELECT coalesce(jsonb_agg(jsonb_build_object('rule_code', rule_code, 'jira_key', jira_key)), '[]')
                   FROM dq.incidents WHERE resolved_run = r.run_id))
  FROM dq.runs r WHERE r.run_id = p_run;
$$;

-- Everything the HTML report needs, in one call. p_run = a past run to show (default: the latest).
DROP FUNCTION IF EXISTS dq.report(int);
CREATE OR REPLACE FUNCTION dq.report(p_history int DEFAULT 14, p_run int DEFAULT NULL) RETURNS jsonb LANGUAGE sql STABLE AS $$
  WITH shown AS (SELECT coalesce(p_run, (SELECT max(run_id) FROM dq.runs WHERE status = 'finished')) AS run_id)
  SELECT jsonb_build_object(
    'latest', (SELECT dq.run_summary(run_id) FROM shown),
    'rules', (SELECT jsonb_agg(jsonb_build_object('rule_code', ru.rule_code, 'rule_name', ru.rule_name, 'dimension', ru.dimension,
                       'severity', ru.severity, 'table_name', ru.table_name, 'status', res.status, 'failing_count', res.failing_count)
                     ORDER BY ru.table_name, ru.rule_code)
                FROM dq.rules ru
                LEFT JOIN dq.results res ON res.rule_code = ru.rule_code AND res.run_id = (SELECT run_id FROM shown)
               WHERE ru.active),
    'history', (SELECT coalesce(jsonb_agg(h ORDER BY h.run_id), '[]') FROM (
                  SELECT run_id, started_at, checks_run, checks_failed, checks_errored, cost_usd
                    FROM dq.runs WHERE status = 'finished' ORDER BY run_id DESC LIMIT p_history) h),
    'open_incidents', (SELECT count(*) FROM dq.incidents WHERE status = 'open'));
$$;

-- ───────────────────────────── views for dashboards (Metabase, Power BI) ─────────────────────────────
CREATE OR REPLACE VIEW dq.v_run_history AS
  SELECT run_id, trigger, started_at, checks_run, checks_failed, checks_errored,
         round(100.0 * (checks_run - checks_failed - checks_errored) / nullif(checks_run, 0), 1) AS pass_rate_pct,
         input_tokens, output_tokens, cost_usd
    FROM dq.runs WHERE status = 'finished';

CREATE OR REPLACE VIEW dq.v_latest_results AS
  SELECT ru.table_name, ru.rule_code, ru.rule_name, ru.dimension, ru.severity, res.status, res.failing_count
    FROM dq.results res JOIN dq.rules ru USING (rule_code)
   WHERE res.run_id = (SELECT max(run_id) FROM dq.runs WHERE status = 'finished');

CREATE OR REPLACE VIEW dq.v_open_incidents AS
  SELECT i.incident_id, i.rule_code, ru.rule_name, ru.severity, ru.owner, i.jira_key, i.first_count, i.last_count,
         i.opened_at, i.explanation->>'likely_cause' AS likely_cause
    FROM dq.incidents i JOIN dq.rules ru USING (rule_code)
   WHERE i.status = 'open';
