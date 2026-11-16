// NODE: "Read decision"  (Code node, mode: Run Once for All Items)
// Accepts the review form (URL-encoded) or JSON: { application_id, decision: approve | reject | request_documents, reviewer, note }
const body = $input.first().json.body || {};
return [{ json: {
  application_id: parseInt(body.application_id, 10) || 0,
  decision: String(body.decision || '').toLowerCase(),
  reviewer: String(body.reviewer || '').slice(0, 100),
  note: String(body.note || '').slice(0, 1000),
  fromForm: String($input.first().json.headers?.['content-type'] || '').includes('form'),
} }];
