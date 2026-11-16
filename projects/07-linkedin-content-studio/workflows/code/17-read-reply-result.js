// NODE: "Read reply result"  (Code node, mode: Run Once for Each Item)
const c = $('Build reply').item.json;
const r = $json;
const headers = Object.fromEntries(Object.entries(r.headers || {}).map(([k, v]) => [k.toLowerCase(), v]));
const urn = r.body?.commentUrn || r.body?.$URN || headers['x-restli-id'] || '';
const report = !r.error && r.statusCode >= 200 && r.statusCode < 300
  ? { event: 'sent', replyUrn: String(urn || 'unknown') }
  : { event: 'failed', stage: 'reply', error: `LinkedIn: ${String(r.error?.message || r.body?.message || `status ${r.statusCode}`).slice(0, 300)}` };
return { json: { id: c.id, report } };
