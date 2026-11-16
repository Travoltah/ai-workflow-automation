// NODE: "Collect comments"  (Code node, mode: Run Once for All Items)
// Only used when the LinkedIn app is allowed to read comments (r_member_social / Community Management API).
// Keeps top-level comments by other people; the website ignores ones it already has.
const who = $('Who am I').first().json;
const me = who?.sub ? `urn:li:person:${who.sub}` : '';
const comments = [];
for (const { json: r } of $input.all()) {
  for (const el of r.elements || []) {
    if (!el || el.actor === me || el.parentComment) continue;
    const urn = el.commentUrn || (el.object && el.id ? `urn:li:comment:(${el.object},${el.id})` : '');
    const text = el.message?.text || '';
    if (!urn || !text.trim()) continue;
    const profile = el['actor~'] || {};
    const name = [profile.localizedFirstName, profile.localizedLastName].filter(Boolean).join(' ') || el.actorName || 'LinkedIn member';
    const when = el.created?.time ? new Date(el.created.time).toISOString() : undefined;
    comments.push({ commentUrn: urn, postUrn: el.object, authorName: name, text, ...(when ? { commentedAt: when } : {}) });
  }
}
return comments.length ? [{ json: { comments } }] : [];
