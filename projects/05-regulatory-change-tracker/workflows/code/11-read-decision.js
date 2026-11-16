// NODE: "Read decision"  (Code node, mode: Run Once for All Items)
// Accepts the review form (application/x-www-form-urlencoded) or JSON from an API client.
const body = $input.first().json.body || {};
const fromForm = String($input.first().json.headers?.['content-type'] || '').includes('form');
return [{ json: {
  change_id: parseInt(body.change_id, 10) || 0,
  decision: String(body.decision || '').toLowerCase(),
  reviewer: String(body.reviewer || '').slice(0, 100),
  note: String(body.note || '').slice(0, 1000),
  fromForm,
} }];
