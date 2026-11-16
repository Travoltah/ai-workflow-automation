// NODE: "Split work"  (Code node, mode: Run Once for All Items)
// Turns the website's check-in into one item per piece of work. The website has already claimed each piece,
// so a second run started at the same time gets different work (or none).
const s = $('Settings').first().json;
const jobs = $('Check in').first().json;
if (jobs.error || !Array.isArray(jobs.generate)) {
  throw new Error(`Couldn't check in with the website: ${String(jobs.error?.message || jobs.error || 'unexpected answer').slice(0, 300)}`);
}
const who = $('Who am I').isExecuted ? $('Who am I').first().json : null;
const me = who && who.sub ? `urn:li:person:${who.sub}` : '';

const out = [];
for (const g of jobs.generate) out.push({ kind: 'generate', ...g });
for (const d of jobs.drafts || []) out.push({ kind: 'draft_reply', ...d });
// LinkedIn work needs to know who is posting. If that call failed, leave the work: the claims expire after
// 30 minutes and the next run picks it up again.
if (me) {
  for (const p of jobs.publish || []) out.push({ kind: 'publish', me, siteUrl: jobs.siteUrl, ...p });
  for (const r of jobs.replies || []) out.push({ kind: 'reply', me, ...r });
  for (const l of jobs.likes || []) out.push({ kind: 'like', me, ...l });
  if (s.readComments) for (const w of jobs.watch || []) out.push({ kind: 'watch', me, ...w });
}
return out.map((json) => ({ json }));
