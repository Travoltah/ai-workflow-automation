// NODE: "Read post result"  (Code node, mode: Run Once for Each Item)
// LinkedIn answers 201 with the new post's URN in the x-restli-id header.
const p = $('Build post').item.json;
const r = $json; // full response
const headers = Object.fromEntries(Object.entries(r.headers || {}).map(([k, v]) => [k.toLowerCase(), v]));
const urn = headers['x-restli-id'] || headers['x-linkedin-id'] || r.body?.id || '';
if (!r.error && r.statusCode === 201 && /^urn:li:(share|ugcPost):/.test(urn)) {
  return { json: { id: p.id, report: { event: 'published', linkedinUrn: urn, linkedinUrl: `https://www.linkedin.com/feed/update/${urn}/` } } };
}
const msg = r.error?.message || r.body?.message || `status ${r.statusCode}`;
return { json: { id: p.id, report: { event: 'publish_failed', error: `LinkedIn didn't create the post: ${String(msg).slice(0, 300)}` } } };
