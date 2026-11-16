-- Regulatory change tracker: schema and the functions n8n calls.
-- The collector service (service/) writes sources' fetch results, documents, versions and changes.
-- n8n reads the changes, stores the AI triage and briefs, and records review decisions and tasks.

\connect reg_tracker

CREATE SCHEMA IF NOT EXISTS reg;

-- ───────────────────────────── reference data ─────────────────────────────
CREATE TABLE IF NOT EXISTS reg.jurisdictions (
  code        text PRIMARY KEY,           -- EU, US, UK, AU, ZW, ZA …
  name        text NOT NULL,
  legal_note  text NOT NULL               -- how law works there; given to the model as context
);

CREATE TABLE IF NOT EXISTS reg.sources (
  source_id          serial PRIMARY KEY,
  code               text UNIQUE NOT NULL,
  jurisdiction       text NOT NULL REFERENCES reg.jurisdictions(code),
  regulator          text NOT NULL,
  name               text NOT NULL,
  method             text NOT NULL CHECK (method IN ('rss', 'json_api', 'html_index', 'html_page')),
  url                text NOT NULL,
  config             jsonb NOT NULL DEFAULT '{}',   -- field mapping, link selector, ignore patterns, max items
  topics             text[] NOT NULL DEFAULT '{}',
  active             boolean NOT NULL DEFAULT true,
  is_mock            boolean NOT NULL DEFAULT false,
  check_every_hours  int NOT NULL DEFAULT 24,
  last_checked_at    timestamptz,
  last_status        text,
  last_error         text,
  last_item_count    int
);

CREATE TABLE IF NOT EXISTS reg.controls (
  control_id   text PRIMARY KEY,
  name         text NOT NULL,
  description  text NOT NULL,
  domain       text NOT NULL,
  owner        text NOT NULL
);

CREATE TABLE IF NOT EXISTS reg.company_profile (
  id             int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  name           text NOT NULL,
  sector         text NOT NULL,
  markets        text[] NOT NULL,           -- where the company operates: changes here are in scope
  watch_markets  text[] NOT NULL,           -- planned or partner markets: tracked at lower priority
  ai_uses        text[] NOT NULL,
  data_types     text[] NOT NULL,
  description    text NOT NULL
);

-- ───────────────────────────── what the collector finds ─────────────────────────────
CREATE TABLE IF NOT EXISTS reg.runs (
  run_id            serial PRIMARY KEY,
  trigger           text NOT NULL,
  started_at        timestamptz NOT NULL DEFAULT now(),
  finished_at       timestamptz,
  status            text NOT NULL DEFAULT 'running',
  sources_checked   int DEFAULT 0,
  sources_failed    int DEFAULT 0,
  changes_detected  int DEFAULT 0,
  changes_relevant  int DEFAULT 0,
  changes_analysed  int DEFAULT 0,
  usage             jsonb NOT NULL DEFAULT '{}',   -- tokens per model
  cost_usd          numeric(8,4) NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS reg.source_checks (
  run_id        int REFERENCES reg.runs(run_id) ON DELETE CASCADE,
  source_id     int REFERENCES reg.sources(source_id),
  status        text NOT NULL CHECK (status IN ('baseline', 'ok', 'empty', 'error')),
  items_seen    int NOT NULL DEFAULT 0,
  new_docs      int NOT NULL DEFAULT 0,
  amended_docs  int NOT NULL DEFAULT 0,
  error         text,
  duration_ms   int,
  PRIMARY KEY (run_id, source_id)
);

CREATE TABLE IF NOT EXISTS reg.documents (
  doc_id          serial PRIMARY KEY,
  source_id       int NOT NULL REFERENCES reg.sources(source_id),
  url             text NOT NULL,
  title           text NOT NULL,
  published_at    date,
  version         int NOT NULL DEFAULT 1,
  current_hash    text NOT NULL,
  current_text    text NOT NULL,
  first_seen_run  int REFERENCES reg.runs(run_id),
  last_changed_run int REFERENCES reg.runs(run_id),
  UNIQUE (source_id, url)
);

CREATE TABLE IF NOT EXISTS reg.document_versions (
  doc_id   int REFERENCES reg.documents(doc_id) ON DELETE CASCADE,
  version  int NOT NULL,
  hash     text NOT NULL,
  text     text NOT NULL,
  run_id   int REFERENCES reg.runs(run_id),
  PRIMARY KEY (doc_id, version)
);

CREATE TABLE IF NOT EXISTS reg.changes (
  change_id      serial PRIMARY KEY,
  run_id         int NOT NULL REFERENCES reg.runs(run_id),
  doc_id         int NOT NULL REFERENCES reg.documents(doc_id),
  version        int NOT NULL,
  change_type    text NOT NULL CHECK (change_type IN ('new', 'amended')),
  diff_text      text NOT NULL,               -- the new document, or only the changed passages
  status         text NOT NULL DEFAULT 'detected'
                 CHECK (status IN ('detected', 'not_relevant', 'relevant', 'analysed', 'flagged', 'approved', 'dismissed')),
  triage         jsonb,
  brief          jsonb,                       -- the AI brief, after the code check
  verification   jsonb,                       -- what the check removed or flagged, and why
  applicability  text,                        -- in_market | watch_market | out_of_scope (calculated by code)
  priority       text,                        -- high | medium | low (calculated by code)
  reviewed_by    text,
  reviewed_at    timestamptz,
  review_note    text,
  created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS reg.tasks (
  task_id     serial PRIMARY KEY,
  change_id   int NOT NULL REFERENCES reg.changes(change_id),
  control_id  text NOT NULL REFERENCES reg.controls(control_id),
  owner       text NOT NULL,
  due_date    date,
  why         text,
  jira_key    text,
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (change_id, control_id)
);

-- ───────────────────────────── functions called by n8n ─────────────────────────────

-- Opens a run and returns the sources due for a check (all active sources when p_force).
CREATE OR REPLACE FUNCTION reg.start_run(p_trigger text, p_force boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE v_run int;
BEGIN
  INSERT INTO reg.runs (trigger) VALUES (p_trigger) RETURNING run_id INTO v_run;
  RETURN jsonb_build_object('run_id', v_run, 'sources', (
    SELECT coalesce(jsonb_agg(jsonb_build_object('source_id', source_id, 'code', code, 'jurisdiction', jurisdiction,
                                                 'regulator', regulator, 'method', method) ORDER BY source_id), '[]')
      FROM reg.sources
     WHERE active AND (p_force OR last_checked_at IS NULL OR last_checked_at < now() - make_interval(hours => check_every_hours))));
END $$;

-- Everything the AI steps need about this run's changes.
CREATE OR REPLACE FUNCTION reg.run_changes(p_run int, p_text_limit int DEFAULT 60000) RETURNS jsonb LANGUAGE sql STABLE AS $$
  SELECT jsonb_build_object(
    'run_id', p_run,
    'source_checks', (SELECT coalesce(jsonb_agg(jsonb_build_object('code', s.code, 'jurisdiction', s.jurisdiction, 'status', sc.status,
                                     'items_seen', sc.items_seen, 'new_docs', sc.new_docs, 'amended_docs', sc.amended_docs, 'error', sc.error)
                                     ORDER BY s.source_id), '[]')
                        FROM reg.source_checks sc JOIN reg.sources s USING (source_id) WHERE sc.run_id = p_run),
    'changes', (SELECT coalesce(jsonb_agg(jsonb_build_object(
                  'change_id', c.change_id, 'change_type', c.change_type, 'version', c.version,
                  'jurisdiction', s.jurisdiction, 'jurisdiction_name', j.name, 'legal_note', j.legal_note,
                  'regulator', s.regulator, 'source', s.code, 'source_topics', s.topics,
                  'title', d.title, 'url', d.url, 'published_at', d.published_at,
                  'diff_text', c.diff_text, 'document_text', left(d.current_text, p_text_limit)) ORDER BY c.change_id), '[]')
                  FROM reg.changes c JOIN reg.documents d USING (doc_id) JOIN reg.sources s USING (source_id)
                  JOIN reg.jurisdictions j ON j.code = s.jurisdiction
                 WHERE c.run_id = p_run),
    'controls', (SELECT jsonb_agg(jsonb_build_object('control_id', control_id, 'name', name, 'description', description,
                                  'domain', domain, 'owner', owner) ORDER BY control_id) FROM reg.controls),
    'profile', (SELECT to_jsonb(p) - 'id' FROM reg.company_profile p));
$$;

-- [{change_id, relevant, triage}]
CREATE OR REPLACE FUNCTION reg.save_triage(p jsonb) RETURNS int LANGUAGE sql AS $$
  WITH upd AS (
    UPDATE reg.changes c SET triage = e.value->'triage',
           status = CASE WHEN (e.value->>'relevant')::boolean THEN 'relevant' ELSE 'not_relevant' END
      FROM jsonb_array_elements(p) e WHERE c.change_id = (e.value->>'change_id')::int AND c.status = 'detected'
    RETURNING 1)
  SELECT count(*)::int FROM upd;
$$;

-- [{change_id, brief, verification, status (analysed|flagged), applicability, priority}]
CREATE OR REPLACE FUNCTION reg.save_briefs(p jsonb) RETURNS int LANGUAGE sql AS $$
  WITH upd AS (
    UPDATE reg.changes c SET brief = e.value->'brief', verification = e.value->'verification', status = e.value->>'status',
           applicability = e.value->>'applicability', priority = e.value->>'priority'
      FROM jsonb_array_elements(p) e WHERE c.change_id = (e.value->>'change_id')::int AND c.status = 'relevant'
    RETURNING 1)
  SELECT count(*)::int FROM upd;
$$;

CREATE OR REPLACE FUNCTION reg.finish_run(p_run int, p_usage jsonb, p_cost numeric) RETURNS jsonb LANGUAGE plpgsql AS $$
BEGIN
  UPDATE reg.runs r SET finished_at = now(), status = 'finished', usage = coalesce(p_usage, '{}'), cost_usd = coalesce(p_cost, 0),
         sources_checked  = (SELECT count(*) FROM reg.source_checks WHERE run_id = p_run),
         sources_failed   = (SELECT count(*) FROM reg.source_checks WHERE run_id = p_run AND status = 'error'),
         changes_detected = (SELECT count(*) FROM reg.changes WHERE run_id = p_run),
         changes_relevant = (SELECT count(*) FROM reg.changes WHERE run_id = p_run AND status IN ('relevant', 'analysed', 'flagged', 'approved', 'dismissed')),
         changes_analysed = (SELECT count(*) FROM reg.changes WHERE run_id = p_run AND brief IS NOT NULL)
   WHERE run_id = p_run;
  RETURN reg.run_summary(p_run);
END $$;

CREATE OR REPLACE FUNCTION reg.run_summary(p_run int) RETURNS jsonb LANGUAGE sql STABLE AS $$
  SELECT jsonb_build_object(
    'run_id', r.run_id, 'trigger', r.trigger, 'started_at', r.started_at, 'finished_at', r.finished_at,
    'sources_checked', r.sources_checked, 'sources_failed', r.sources_failed, 'changes_detected', r.changes_detected,
    'changes_relevant', r.changes_relevant, 'changes_analysed', r.changes_analysed, 'usage', r.usage, 'cost_usd', r.cost_usd,
    'source_checks', (SELECT coalesce(jsonb_agg(jsonb_build_object('code', s.code, 'jurisdiction', s.jurisdiction, 'status', sc.status,
                                      'items_seen', sc.items_seen, 'error', sc.error) ORDER BY s.source_id), '[]')
                        FROM reg.source_checks sc JOIN reg.sources s USING (source_id) WHERE sc.run_id = r.run_id),
    'changes', (SELECT coalesce(jsonb_agg(jsonb_build_object(
                  'change_id', c.change_id, 'jurisdiction', s.jurisdiction, 'regulator', s.regulator, 'title', d.title, 'url', d.url,
                  'change_type', c.change_type, 'status', c.status, 'relevant', (c.triage->>'relevant')::boolean,
                  'triage_reason', c.triage->>'reason', 'applicability', c.applicability, 'priority', c.priority,
                  'brief', c.brief, 'verification', c.verification)
                  ORDER BY array_position(ARRAY['high', 'medium', 'low'], c.priority), c.change_id), '[]')
                  FROM reg.changes c JOIN reg.documents d USING (doc_id) JOIN reg.sources s USING (source_id)
                 WHERE c.run_id = r.run_id))
  FROM reg.runs r WHERE r.run_id = p_run;
$$;

-- Briefs waiting for a human decision.
CREATE OR REPLACE FUNCTION reg.review_queue() RETURNS jsonb LANGUAGE sql STABLE AS $$
  SELECT coalesce(jsonb_agg(jsonb_build_object(
           'change_id', c.change_id, 'run_id', c.run_id, 'jurisdiction', s.jurisdiction, 'regulator', s.regulator,
           'title', d.title, 'url', d.url, 'change_type', c.change_type, 'status', c.status,
           'applicability', c.applicability, 'priority', c.priority, 'brief', c.brief, 'verification', c.verification)
         ORDER BY array_position(ARRAY['high', 'medium', 'low'], c.priority), c.change_id), '[]')
    FROM reg.changes c JOIN reg.documents d USING (doc_id) JOIN reg.sources s USING (source_id)
   WHERE c.status IN ('analysed', 'flagged');
$$;

-- Records a reviewer's decision. On approval, creates one task per mapped control and returns them for Jira.
-- A decision can be made once; a second attempt returns ok = false.
CREATE OR REPLACE FUNCTION reg.decide(p_change int, p_decision text, p_reviewer text, p_note text)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE c reg.changes%ROWTYPE; v_due date;
BEGIN
  SELECT * INTO c FROM reg.changes WHERE change_id = p_change FOR UPDATE;
  IF NOT FOUND THEN RETURN jsonb_build_object('ok', false, 'error', 'No such change'); END IF;
  IF c.status NOT IN ('analysed', 'flagged') THEN
    RETURN jsonb_build_object('ok', false, 'error', format('Change %s is %s and cannot be reviewed', p_change, c.status));
  END IF;
  IF p_decision NOT IN ('approve', 'dismiss') THEN RETURN jsonb_build_object('ok', false, 'error', 'Decision must be approve or dismiss'); END IF;
  IF coalesce(btrim(p_reviewer), '') = '' THEN RETURN jsonb_build_object('ok', false, 'error', 'Reviewer name is required'); END IF;

  UPDATE reg.changes SET status = CASE p_decision WHEN 'approve' THEN 'approved' ELSE 'dismissed' END,
         reviewed_by = p_reviewer, reviewed_at = now(), review_note = p_note
   WHERE change_id = p_change;

  IF p_decision = 'approve' THEN
    -- the earliest compliance / effective / comment date in the brief is the task due date
    SELECT min((k->>'date')::date) INTO v_due FROM jsonb_array_elements(coalesce(c.brief->'key_dates', '[]')) k
     WHERE k->>'type' IN ('effective', 'compliance_deadline', 'comment_deadline') AND (k->>'date') ~ '^\d{4}-\d{2}-\d{2}$';
    INSERT INTO reg.tasks (change_id, control_id, owner, due_date, why)
    SELECT p_change, ac->>'control_id', ct.owner, v_due, ac->>'why'
      FROM jsonb_array_elements(coalesce(c.brief->'affected_controls', '[]')) ac
      JOIN reg.controls ct ON ct.control_id = ac->>'control_id'
    ON CONFLICT DO NOTHING;
  END IF;

  RETURN jsonb_build_object('ok', true, 'change_id', p_change, 'decision', p_decision,
    'change', (SELECT jsonb_build_object('title', d.title, 'url', d.url, 'jurisdiction', s.jurisdiction, 'regulator', s.regulator,
                                         'priority', c.priority, 'brief', c.brief)
                 FROM reg.documents d JOIN reg.sources s USING (source_id) WHERE d.doc_id = c.doc_id),
    'tasks', (SELECT coalesce(jsonb_agg(jsonb_build_object('task_id', t.task_id, 'control_id', t.control_id, 'control_name', ct.name,
                                        'owner', t.owner, 'due_date', t.due_date, 'why', t.why) ORDER BY t.control_id), '[]')
                FROM reg.tasks t JOIN reg.controls ct USING (control_id) WHERE t.change_id = p_change AND t.jira_key IS NULL));
END $$;

-- [{task_id, jira_key}]
CREATE OR REPLACE FUNCTION reg.record_task_keys(p jsonb) RETURNS int LANGUAGE sql AS $$
  WITH upd AS (
    UPDATE reg.tasks t SET jira_key = e.value->>'jira_key'
      FROM jsonb_array_elements(p) e WHERE t.task_id = (e.value->>'task_id')::int AND coalesce(e.value->>'jira_key', '') <> ''
    RETURNING 1)
  SELECT count(*)::int FROM upd;
$$;

-- Everything the HTML report needs. p_run = an earlier run to show (default: the latest).
DROP FUNCTION IF EXISTS reg.report();
CREATE OR REPLACE FUNCTION reg.report(p_run int DEFAULT NULL) RETURNS jsonb LANGUAGE sql STABLE AS $$
  SELECT jsonb_build_object(
    'latest', (SELECT reg.run_summary(coalesce(p_run, max(run_id))) FROM reg.runs WHERE status = 'finished'),
    'sources', (SELECT jsonb_agg(jsonb_build_object('code', code, 'jurisdiction', jurisdiction, 'regulator', regulator, 'name', name,
                         'method', method, 'is_mock', is_mock, 'active', active, 'last_checked_at', last_checked_at,
                         'last_status', last_status, 'last_error', last_error, 'last_item_count', last_item_count)
                       ORDER BY active DESC, jurisdiction, code) FROM reg.sources),
    'by_jurisdiction', (SELECT coalesce(jsonb_agg(x ORDER BY x->>'jurisdiction'), '[]') FROM (
        SELECT jsonb_build_object('jurisdiction', s.jurisdiction,
               'changes', count(c.change_id), 'relevant', count(*) FILTER (WHERE c.status NOT IN ('detected', 'not_relevant')),
               'pending_review', count(*) FILTER (WHERE c.status IN ('analysed', 'flagged')),
               'approved', count(*) FILTER (WHERE c.status = 'approved')) AS x
          FROM reg.changes c JOIN reg.documents d USING (doc_id) JOIN reg.sources s USING (source_id)
         WHERE c.created_at > now() - interval '90 days' GROUP BY s.jurisdiction) q),
    'deadlines', (SELECT coalesce(jsonb_agg(jsonb_build_object('date', k->>'date', 'type', k->>'type', 'title', d.title,
                         'jurisdiction', s.jurisdiction, 'change_id', c.change_id, 'status', c.status, 'priority', c.priority)
                         ORDER BY k->>'date'), '[]')
                    FROM reg.changes c JOIN reg.documents d USING (doc_id) JOIN reg.sources s USING (source_id),
                         jsonb_array_elements(coalesce(c.brief->'key_dates', '[]')) k
                   WHERE c.status IN ('analysed', 'flagged', 'approved') AND (k->>'date') ~ '^\d{4}-\d{2}-\d{2}$'
                     AND (k->>'date')::date >= current_date),
    'pending_review', (SELECT count(*) FROM reg.changes WHERE status IN ('analysed', 'flagged')),
    'open_tasks', (SELECT count(*) FROM reg.tasks),
    'history', (SELECT coalesce(jsonb_agg(h ORDER BY h.run_id), '[]') FROM (
                  SELECT run_id, started_at, sources_checked, sources_failed, changes_detected, changes_relevant, cost_usd
                    FROM reg.runs WHERE status = 'finished' ORDER BY run_id DESC LIMIT 14) h));
$$;

-- ───────────────────────────── views for dashboards ─────────────────────────────
CREATE OR REPLACE VIEW reg.v_upcoming_deadlines AS
  SELECT (k->>'date')::date AS deadline, k->>'type' AS deadline_type, s.jurisdiction, s.regulator, d.title, c.change_id, c.status, c.priority
    FROM reg.changes c JOIN reg.documents d USING (doc_id) JOIN reg.sources s USING (source_id),
         jsonb_array_elements(coalesce(c.brief->'key_dates', '[]')) k
   WHERE (k->>'date') ~ '^\d{4}-\d{2}-\d{2}$' AND c.status IN ('analysed', 'flagged', 'approved');

CREATE OR REPLACE VIEW reg.v_changes AS
  SELECT c.change_id, c.run_id, c.created_at, s.jurisdiction, s.regulator, d.title, d.url, c.change_type, c.status,
         c.applicability, c.priority, c.brief->>'summary' AS summary, c.reviewed_by, c.reviewed_at
    FROM reg.changes c JOIN reg.documents d USING (doc_id) JOIN reg.sources s USING (source_id);
