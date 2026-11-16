// NODE: "Read draft"  (Code node, mode: Run Once for Each Item)
// Parses Claude's answer into the draft the website stores. A failed, refused or cut-off call becomes a
// "failed" report (the website retries it up to three times), never a half-finished draft.
const s = $('Settings').first().json;
const req = $('Build draft request').item.json;
const res = $json;
const PRICES = { 'claude-opus-5-5': [4, 20], 'claude-haiku-5-5': [0.1, 0.5] }; // USD per million tokens
const u = res.usage || {};
const [pin, pout] = PRICES[s.model] || PRICES['claude-opus-5-5'];
const inTok = (u.input_tokens || 0) + (u.cache_read_input_tokens || 0) + (u.cache_creation_input_tokens || 0);
const cost = Math.round(((inTok * pin + (u.output_tokens || 0) * pout) / 1e6) * 10000) / 10000;

const fail = (error) => ({ json: { id: req.id, format: req.format, failed: true, error, cost, model: s.model } });
if (res.error) return fail(`Claude call failed: ${String(res.error.message || res.error.description || res.error).slice(0, 300)}`);
if (res.stop_reason !== 'end_turn') return fail(`Claude's answer was incomplete (${res.stop_reason}).`);
let a;
try {
  a = JSON.parse(res.content.find((b) => b.type === 'text').text);
} catch (e) {
  return fail('Claude returned invalid JSON.');
}

const slugify = (t) => String(t || '').toLowerCase().normalize('NFKD').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 80);
const clean = (t) => String(t || '').trim();
// The model's flat diagram becomes the layout the website draws. Too few items falls back to the closest layout.
function toVisual(v) {
  const items = (v?.items || []).filter((i) => i && clean(i.label)).map((i) => ({ label: clean(i.label), note: clean(i.note) }));
  if (v?.type === 'venn' && items.length >= 2) return { type: 'venn', left: items[0], right: items[1], overlap: clean(v.center) || 'Overlap' };
  if (v?.type === 'foundation' && items.length >= 2) {
    return { type: 'foundation', top: clean(v.center), pillars: items.slice(0, 4).map((i) => i.label), base: clean(v.base) || 'Foundation', chips: (v.chips || []).map(clean).filter(Boolean).slice(0, 5) };
  }
  if (items.length >= 3) return { type: 'flow', steps: items.slice(0, 5) };
  if (items.length === 2) return { type: 'venn', left: items[0], right: items[1], overlap: clean(v?.center) || 'Overlap' };
  return { type: 'flow', steps: items }; // invalid on purpose: the website flags it for the reviewer
}

const c = a.cover || {};
const coverSpec = { eyebrow: clean(c.eyebrow), title: clean(c.title), highlight: clean(c.highlight), subtitle: clean(c.subtitle), caption: clean(c.caption), visual: toVisual(c.visual) };
let infographicSpec = null;
if (req.format === 'ARTICLE' && a.infographic) {
  const g = a.infographic;
  infographicSpec = {
    kicker: clean(g.kicker), title: coverSpec.title, highlight: coverSpec.highlight, subtitle: clean(g.subtitle), section1: clean(g.section1),
    visual: toVisual(g.visual), noteBold: clean(g.note_bold), note: clean(g.note),
    bad: { title: clean(g.bad_title), items: (g.bad_items || []).map(clean).filter(Boolean).slice(0, 4) },
    good: { title: clean(g.good_title), items: (g.good_items || []).map(clean).filter(Boolean).slice(0, 4) },
    section2: clean(g.section2),
    cards: (g.cards || []).filter((x) => x && clean(x.label)).slice(0, 5).map((x) => ({ label: clean(x.label), text: clean(x.text) })),
    closing: clean(g.closing), closingHighlight: clean(g.closing_highlight),
  };
}
const draft = {
  title: clean(a.title) || clean(a.topic),
  slug: req.format === 'ARTICLE' ? slugify(a.slug || a.title) : null,
  excerpt: req.format === 'ARTICLE' ? clean(a.excerpt) : null,
  body: req.format === 'ARTICLE' ? clean(a.article) : null,
  linkedinText: clean(a.linkedin_post),
  tags: (a.tags || []).map((t) => String(t).replace(/[^A-Za-z0-9]/g, '')).filter(Boolean).slice(0, 5),
  coverSpec,
  infographicSpec,
};
return { json: { id: req.id, format: req.format, failed: false, draft, cost, model: s.model } };
