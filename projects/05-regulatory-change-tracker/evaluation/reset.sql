-- Empties every run, document, change and task, so the tracker starts from scratch (the next check is a baseline).
-- Keeps the reference data: jurisdictions, sources, controls and the company profile.
\connect reg_tracker
TRUNCATE reg.tasks, reg.changes, reg.document_versions, reg.documents, reg.source_checks, reg.runs RESTART IDENTITY;
UPDATE reg.sources SET last_checked_at = NULL, last_status = NULL, last_error = NULL, last_item_count = NULL;
