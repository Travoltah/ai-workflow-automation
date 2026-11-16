// NODE: "Read like result"  (Code node, mode: Run Once for Each Item)
// 409 means the comment is already liked: that counts as done.
const c = $('Build like').item.json;
const r = $json;
const ok = !r.error && ((r.statusCode >= 200 && r.statusCode < 300) || r.statusCode === 409);
const report = ok ? { event: 'liked' } : { event: 'failed', stage: 'like', error: `LinkedIn: ${String(r.error?.message || `status ${r.statusCode}`).slice(0, 300)}` };
return { json: { id: c.id, report } };
