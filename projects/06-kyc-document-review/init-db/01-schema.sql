-- KYC document review: schema and the functions n8n calls.
-- The intake service writes documents, pages and checks; n8n writes AI extractions and review decisions.
-- Passwords are NEVER stored: the audit log only records that one was supplied, by whom and when.

\connect kyc

CREATE SCHEMA IF NOT EXISTS kyc;

CREATE TABLE IF NOT EXISTS kyc.settings (
  key    text PRIMARY KEY,
  value  jsonb NOT NULL
);

CREATE TABLE IF NOT EXISTS kyc.applications (
  application_id  serial PRIMARY KEY,
  reference       text UNIQUE NOT NULL,
  applicant       jsonb NOT NULL,             -- what the customer typed: full_name, date_of_birth, address
  status          text NOT NULL DEFAULT 'received'
                  CHECK (status IN ('received', 'processing', 'action_required', 'ready_for_review', 'approved', 'rejected', 'documents_requested')),
  check_summary   jsonb,
  customer_actions jsonb,
  decision        text,
  reviewed_by     text,
  reviewed_at     timestamptz,
  review_note     text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS kyc.documents (
  document_id        serial PRIMARY KEY,
  application_id     int NOT NULL REFERENCES kyc.applications(application_id) ON DELETE CASCADE,
  filename           text NOT NULL,
  declared_type      text CHECK (declared_type IN ('identity', 'proof_of_address', 'other')),
  mime               text,
  size_bytes         int,
  sha256             text,
  file               bytea NOT NULL,          -- the original upload, for audit (encrypt or move to object storage in production)
  status             text NOT NULL
                     CHECK (status IN ('ok', 'needs_password', 'password_locked', 'poor_quality', 'unsupported_type', 'corrupt', 'rejected_macro')),
  status_reason      text,
  encryption         text,                    -- none | restricted | password
  password_attempts  int NOT NULL DEFAULT 0,
  extension_mismatch boolean NOT NULL DEFAULT false,
  scanned            boolean,
  digital_text       text,
  pdf_meta           jsonb,
  page_count         int,
  created_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS kyc.pages (
  document_id  int REFERENCES kyc.documents(document_id) ON DELETE CASCADE,
  page_no      int NOT NULL,
  ai_jpeg      bytea NOT NULL,                -- sent to the model (longest edge 1,568 px)
  thumb_jpeg   bytea NOT NULL,                -- shown to the reviewer
  quality      jsonb,
  PRIMARY KEY (document_id, page_no)
);

CREATE TABLE IF NOT EXISTS kyc.extractions (
  document_id   int PRIMARY KEY REFERENCES kyc.documents(document_id) ON DELETE CASCADE,
  model         text,
  doc_type      text,
  readability   text,
  fields        jsonb NOT NULL,               -- {field: {value, as_printed, confidence}}
  notes         text,
  verification  jsonb,                        -- what the code check could and couldn't confirm
  usage         jsonb,
  cost_usd      numeric(8,4),
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS kyc.checks (
  check_id        serial PRIMARY KEY,
  application_id  int NOT NULL REFERENCES kyc.applications(application_id) ON DELETE CASCADE,
  document_id     int REFERENCES kyc.documents(document_id) ON DELETE CASCADE,
  code            text NOT NULL,
  result          text NOT NULL CHECK (result IN ('pass', 'fail', 'warn')),
  severity        text NOT NULL,
  detail          text NOT NULL,
  action          text NOT NULL,              -- customer | reviewer | none
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS kyc.audit_log (
  id              bigserial PRIMARY KEY,
  application_id  int,
  document_id     int,
  event           text NOT NULL,
  actor           text NOT NULL,
  detail          jsonb,
  at              timestamptz NOT NULL DEFAULT now()
);

-- ───────────────────────────── functions called by n8n ─────────────────────────────

CREATE OR REPLACE FUNCTION kyc.create_application(p_reference text, p_applicant jsonb) RETURNS int LANGUAGE plpgsql AS $$
DECLARE v int;
BEGIN
  INSERT INTO kyc.applications (reference, applicant, status) VALUES (p_reference, p_applicant, 'processing') RETURNING application_id INTO v;
  INSERT INTO kyc.audit_log (application_id, event, actor, detail) VALUES (v, 'application_received', 'api', jsonb_build_object('reference', p_reference));
  RETURN v;
END $$;

-- Documents that can be read and haven't been yet.
CREATE OR REPLACE FUNCTION kyc.docs_to_read(p_app int) RETURNS jsonb LANGUAGE sql STABLE AS $$
  SELECT coalesce(jsonb_agg(jsonb_build_object('document_id', d.document_id, 'filename', d.filename, 'declared_type', d.declared_type)
                            ORDER BY d.document_id), '[]')
    FROM kyc.documents d LEFT JOIN kyc.extractions e USING (document_id)
   WHERE d.application_id = p_app AND d.status = 'ok' AND e.document_id IS NULL;
$$;

-- [{document_id, model, doc_type, readability, fields, notes, verification, usage, cost_usd}]
CREATE OR REPLACE FUNCTION kyc.save_extractions(p jsonb) RETURNS int LANGUAGE plpgsql AS $$
DECLARE n int;
BEGIN
  INSERT INTO kyc.extractions (document_id, model, doc_type, readability, fields, notes, verification, usage, cost_usd)
  SELECT (e->>'document_id')::int, e->>'model', e->>'doc_type', e->>'readability', coalesce(e->'fields', '{}'), e->>'notes',
         e->'verification', e->'usage', coalesce((e->>'cost_usd')::numeric, 0)
    FROM jsonb_array_elements(p) e
  ON CONFLICT (document_id) DO UPDATE SET model = EXCLUDED.model, doc_type = EXCLUDED.doc_type, readability = EXCLUDED.readability,
    fields = EXCLUDED.fields, notes = EXCLUDED.notes, verification = EXCLUDED.verification, usage = EXCLUDED.usage, cost_usd = EXCLUDED.cost_usd;
  GET DIAGNOSTICS n = ROW_COUNT;
  INSERT INTO kyc.audit_log (application_id, document_id, event, actor, detail)
  SELECT d.application_id, d.document_id, 'fields_extracted', 'ai:' || coalesce(e->>'model', '?'), jsonb_build_object('doc_type', e->>'doc_type')
    FROM jsonb_array_elements(p) e JOIN kyc.documents d ON d.document_id = (e->>'document_id')::int;
  RETURN n;
END $$;

-- Applications for the review page: newest first (or one, by reference), with documents, thumbnails, fields and checks.
DROP FUNCTION IF EXISTS kyc.review_queue(int);
CREATE OR REPLACE FUNCTION kyc.review_queue(p_limit int DEFAULT 30, p_reference text DEFAULT NULL) RETURNS jsonb LANGUAGE sql STABLE AS $$
  SELECT coalesce(jsonb_agg(x ORDER BY (x->>'application_id')::int DESC), '[]') FROM (
    SELECT jsonb_build_object(
      'application_id', a.application_id, 'reference', a.reference, 'applicant', a.applicant, 'status', a.status,
      'check_summary', a.check_summary, 'customer_actions', a.customer_actions, 'decision', a.decision,
      'reviewed_by', a.reviewed_by, 'created_at', a.created_at,
      'documents', (SELECT coalesce(jsonb_agg(jsonb_build_object(
          'document_id', d.document_id, 'filename', d.filename, 'declared_type', d.declared_type, 'mime', d.mime,
          'status', d.status, 'status_reason', d.status_reason, 'encryption', d.encryption, 'scanned', d.scanned,
          'doc_type', e.doc_type, 'readability', e.readability, 'fields', e.fields, 'notes', e.notes,
          'thumbs', (SELECT coalesce(jsonb_agg(encode(p.thumb_jpeg, 'base64') ORDER BY p.page_no), '[]') FROM kyc.pages p WHERE p.document_id = d.document_id AND p.page_no <= 2))
          ORDER BY d.document_id), '[]')
        FROM kyc.documents d LEFT JOIN kyc.extractions e USING (document_id) WHERE d.application_id = a.application_id),
      'checks', (SELECT coalesce(jsonb_agg(jsonb_build_object('code', c.code, 'result', c.result, 'severity', c.severity, 'detail', c.detail,
                         'action', c.action, 'document_id', c.document_id)
                       ORDER BY array_position(ARRAY['fail', 'warn', 'pass'], c.result), c.code), '[]')
                   FROM kyc.checks c WHERE c.application_id = a.application_id)) AS x
      FROM kyc.applications a WHERE p_reference IS NULL OR a.reference = p_reference ORDER BY a.application_id DESC LIMIT p_limit) q;
$$;

-- A person's decision. Only applications ready for review can be approved; a decision is made once.
CREATE OR REPLACE FUNCTION kyc.decide(p_app int, p_decision text, p_reviewer text, p_note text) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE a kyc.applications%ROWTYPE;
BEGIN
  SELECT * INTO a FROM kyc.applications WHERE application_id = p_app FOR UPDATE;
  IF NOT FOUND THEN RETURN jsonb_build_object('ok', false, 'error', 'No such application'); END IF;
  IF a.decision IS NOT NULL THEN RETURN jsonb_build_object('ok', false, 'error', format('Application %s was already decided: %s', p_app, a.decision)); END IF;
  IF p_decision NOT IN ('approve', 'reject', 'request_documents') THEN RETURN jsonb_build_object('ok', false, 'error', 'Decision must be approve, reject or request_documents'); END IF;
  IF coalesce(btrim(p_reviewer), '') = '' THEN RETURN jsonb_build_object('ok', false, 'error', 'Reviewer name is required'); END IF;
  IF p_decision = 'approve' AND a.status <> 'ready_for_review' THEN
    RETURN jsonb_build_object('ok', false, 'error', format('Application %s is %s: only applications ready for review can be approved', p_app, a.status));
  END IF;
  UPDATE kyc.applications SET decision = p_decision, reviewed_by = p_reviewer, reviewed_at = now(), review_note = p_note, updated_at = now(),
         status = CASE p_decision WHEN 'approve' THEN 'approved' WHEN 'reject' THEN 'rejected' ELSE 'documents_requested' END
   WHERE application_id = p_app;
  INSERT INTO kyc.audit_log (application_id, event, actor, detail)
  VALUES (p_app, 'decision_' || p_decision, p_reviewer, jsonb_build_object('note', p_note, 'failed_checks', a.check_summary->'fail'));
  RETURN jsonb_build_object('ok', true, 'application_id', p_app, 'decision', p_decision, 'reference', a.reference);
END $$;
