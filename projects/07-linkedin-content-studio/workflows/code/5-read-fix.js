// NODE: "Read fix"  (Code node, mode: Run Once for Each Item)
// Takes Claude's corrected text if the call worked; otherwise keeps the first draft (the reviewer sees its problems).
const s = $('Settings').first().json;
const d = $('Fix needed?').item.json;
const res = $json;
const PRICES = { 'claude-opus-5-5': [4, 20], 'claude-haiku-5-5': [0.1, 0.5] };
const u = res.usage || {};
const [pin, pout] = PRICES[s.model] || PRICES['claude-opus-5-5'];
const inTok = (u.input_tokens || 0) + (u.cache_read_input_tokens || 0) + (u.cache_creation_input_tokens || 0);
const cost = Math.round(((inTok * pin + (u.output_tokens || 0) * pout) / 1e6) * 10000) / 10000;
const draft = { ...d.draft };
let fixed = false;
if (!res.error && res.stop_reason === 'end_turn') {
  try {
    const a = JSON.parse(res.content.find((b) => b.type === 'text').text);
    if (a.linkedin_post?.trim()) draft.linkedinText = a.linkedin_post.trim();
    if (d.format === 'ARTICLE' && a.article?.trim()) draft.body = a.article.trim();
    if (a.title?.trim()) draft.title = a.title.trim();
    fixed = true;
  } catch (e) {
    /* keep the first draft */
  }
}
return { json: { id: d.id, body: { event: 'draft', ...draft, model: d.model, costUsd: Math.round((d.cost + cost) * 10000) / 10000 }, fixed } };
