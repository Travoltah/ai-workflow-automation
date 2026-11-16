// NODE: "Read reply fix"  (Code node, mode: Run Once for Each Item)
const s = $('Settings').first().json;
const d = $('Reply fix needed?').item.json;
const res = $json;
const PRICES = { 'claude-opus-5-5': [4, 20], 'claude-haiku-5-5': [0.1, 0.5] };
const u = res.usage || {};
const [pin, pout] = PRICES[s.model] || PRICES['claude-opus-5-5'];
const inTok = (u.input_tokens || 0) + (u.cache_read_input_tokens || 0) + (u.cache_creation_input_tokens || 0);
const cost = Math.round(((inTok * pin + (u.output_tokens || 0) * pout) / 1e6) * 10000) / 10000;
let reply = d.reply;
if (!res.error && res.stop_reason === 'end_turn') {
  try {
    const a = JSON.parse(res.content.find((b) => b.type === 'text').text);
    if (a.reply?.trim()) reply = a.reply.trim();
  } catch (e) {
    /* keep the first draft */
  }
}
return { json: { id: d.id, body: { event: 'drafted', reply, note: d.note, shouldLike: d.shouldLike, costUsd: Math.round((d.cost + cost) * 10000) / 10000 } } };
