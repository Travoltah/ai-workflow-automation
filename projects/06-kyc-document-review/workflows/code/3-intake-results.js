// NODE: "Intake results"  (Code node, mode: Run Once for All Items)
// What intake decided per file (ok, needs_password, poor_quality, unsupported_type, rejected_macro, corrupt).
// Files that aren't "ok" never reach the AI: no cost, and the customer is told what to fix.
const appId = $('Create application').first().json.application_id;
const intake = $input.all().map((i) => (i.json.error
  ? { status: 'intake_error', reason: JSON.stringify(i.json.error).slice(0, 200) }
  : { document_id: i.json.document_id, filename: i.json.filename, status: i.json.status, reason: i.json.reason, encryption: i.json.encryption, pages: i.json.pages }));
return [{ json: { application_id: appId, intake } }];
