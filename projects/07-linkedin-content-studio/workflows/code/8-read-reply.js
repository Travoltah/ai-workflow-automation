// NODE: "Read reply"  (Code node, mode: Run Once for Each Item)
// A failed call is reported (the comment stays new and is drafted again on the next run).
const s = $('Settings').first().json;
const req = $('Build reply request').item.json;
const res = $json;
const PRICES = { 'claude-opus-5-5': [4, 20], 'claude-haiku-5-5': [0.1, 0.5] };
const u = res.usage || {};
const [pin, pout] = PRICES[s.model] || PRICES['claude-opus-5-5'];
const inTok = (u.input_tokens || 0) + (u.cache_read_input_tokens || 0) + (u.cache_creation_input_tokens || 0);
const cost = Math.round(((inTok * pin + (u.output_tokens || 0) * pout) / 1e6) * 10000) / 10000;
const fail = (error) => ({ json: { id: req.id, failed: true, error, cost, reply: '' } });
if (res.error) return fail(`Claude call failed: ${String(res.error.message || res.error).slice(0, 300)}`);
if (res.stop_reason !== 'end_turn') return fail(`Claude's answer was incomplete (${res.stop_reason}).`);
let a;
try {
  a = JSON.parse(res.content.find((b) => b.type === 'text').text);
} catch (e) {
  return fail('Claude returned invalid JSON.');
}
const reply = a.should_reply ? String(a.reply || '').trim() : '';
const note = String(a.note || '').trim() || (a.should_reply ? '' : 'The AI suggests not replying.');
return { json: { id: req.id, failed: false, reply, note, shouldLike: a.should_like === true, cost } };
