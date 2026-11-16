// NODE: "Ready to submit"  (Code node, mode: Run Once for Each Item)
// The draft passed the style check first time, or the Claude call failed (reported, so the website can retry it).
const d = $json;
const body = d.failed ? { event: 'failed', error: d.error, costUsd: d.cost } : { event: 'draft', ...d.draft, model: d.model, costUsd: d.cost };
return { json: { id: d.id, body } };
