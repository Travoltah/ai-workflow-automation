// Offline tests for the workflow's code nodes, using real Claude responses. No API calls, no LinkedIn.
//
// Replays evaluation/fixture-live-run-1.json (the drafts and reply drafts from the first live run) through the
// Code nodes, and checks the LinkedIn request building against the rules LinkedIn enforces.
//
//   node evaluation/test-guardrails.js

const fs = require('fs');
const path = require('path');

const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixture-live-run-1.json'), 'utf8'));
const src = (f) => fs.readFileSync(path.join(__dirname, '..', 'workflows', 'code', f), 'utf8');
const clone = (x) => JSON.parse(JSON.stringify(x));

// A minimal stand-in for n8n's $('Node') / $input / $json.
const nodeRef = (json, all) => ({ first: () => ({ json: json ?? (all && all[0]) }), all: () => (all || [json]).map((j) => ({ json: j })), item: { json }, isExecuted: json !== undefined || !!all });
function run(file, { nodes = {}, json, input } = {}) {
  const $ = (name) => {
    if (!(name in nodes)) return { isExecuted: false, first: () => { throw new Error(`no ${name}`); }, item: { json: undefined } };
    return nodes[name];
  };
  const $input = { all: () => (input || []).map((j) => ({ json: j })) };
  const out = new Function('$', '$input', '$json', src(file))($, $input, json);
  return Array.isArray(out) ? out.map((o) => o.json) : out.json;
}

let failed = 0;
const expect = (name, got, want) => {
  const pass = JSON.stringify(got) === JSON.stringify(want);
  if (!pass) failed++;
  console.log(`${pass ? 'PASS' : 'FAIL'}  ${name}${pass ? '' : `  (got ${JSON.stringify(got)}, expected ${JSON.stringify(want)})`}`);
};

const settings = nodeRef(fixture.settings);
const draftOf = (format) => fixture.drafts.find((d) => d.request.format === format);
const readDraft = (d, response) => run('2-read-draft.js', { nodes: { Settings: settings, 'Build draft request': nodeRef(d.request) }, json: response ?? d.response });
const withAnswer = (d, mutate) => {
  const r = clone(d.response);
  const block = r.content.find((b) => b.type === 'text');
  const a = JSON.parse(block.text); mutate(a); block.text = JSON.stringify(a);
  return r;
};

// ── Read draft ──
const A = draftOf('ARTICLE');
const P = draftOf('POST');
const art = readDraft(A);
expect('article: parsed, not failed', art.failed, false);
expect('article: body keeps the {{INFOGRAPHIC}} marker once', (art.draft.body.match(/\{\{INFOGRAPHIC\}\}/g) || []).length, 1);
expect('article: post keeps the {{LINK}} marker', art.draft.linkedinText.includes('{{LINK}}'), true);
expect('article: slug is URL-safe', /^[a-z0-9-]+$/.test(art.draft.slug), true);
expect('article: cover diagram is a valid venn', [art.draft.coverSpec.visual.type, !!art.draft.coverSpec.visual.left?.label, !!art.draft.coverSpec.visual.right?.label], ['venn', true, true]);
expect('article: infographic has 4 + 4 items and 5 cards', [art.draft.infographicSpec.bad.items.length, art.draft.infographicSpec.good.items.length, art.draft.infographicSpec.cards.length], [4, 4, 5]);
expect('article: cost is counted', art.cost > 0, true);
const post = readDraft(P);
expect('post: no article body or infographic', [post.draft.body, post.draft.infographicSpec], [null, null]);
expect('post: tags have no # or spaces', post.draft.tags.every((t) => /^[A-Za-z0-9]+$/.test(t)), true);

const err = readDraft(A, { error: { message: 'overloaded' } });
expect('a failed call is reported, never stored as a draft', [err.failed, !!err.draft, err.error.includes('overloaded')], [true, false, true]);
const cut = readDraft(A, { ...clone(A.response), stop_reason: 'max_tokens' });
expect('a cut-off answer is reported, and its tokens still costed', [cut.failed, cut.cost > 0], [true, true]);
const bad = readDraft(A, { ...clone(A.response), content: [{ type: 'text', text: '{not json' }] });
expect('invalid JSON is reported', bad.failed, true);
const twoItems = readDraft(A, withAnswer(A, (a) => { a.cover.visual = { type: 'flow', center: '', base: '', items: [{ label: 'One', note: '' }, { label: 'Two', note: '' }], chips: [] }; }));
expect('a 2-step "flow" becomes a venn instead of an invalid layout', twoItems.draft.coverSpec.visual.type, 'venn');
const foundation = readDraft(A, withAnswer(A, (a) => { a.cover.visual = { type: 'foundation', center: 'Roof', base: 'Base', items: [1, 2, 3, 4, 5, 6].map((n) => ({ label: `P${n}`, note: '' })), chips: ['a', 'b', 'c', 'd', 'e', 'f', 'g'] }; }));
expect('foundation keeps at most 4 pillars and 5 chips', [foundation.draft.coverSpec.visual.pillars.length, foundation.draft.coverSpec.visual.chips.length], [4, 5]);

// ── Fix needed? / Ready to submit ──
const fixNeeded = (lint, d = art) => run('3-fix-needed.js', { nodes: { 'Read draft': nodeRef(d) }, json: lint });
expect('clean draft: no fix pass', fixNeeded({ ok: true, errors: [], warnings: [] }).needsFix, false);
expect('style errors: one fix pass', fixNeeded({ ok: false, errors: [{ code: 'dash', message: 'x' }] }).needsFix, true);
expect('a failed draft is never sent for fixing', fixNeeded({ ok: false, errors: [{ code: 'dash' }] }, err).needsFix, false);
expect('a failed draft is reported as failed', run('6-ready-to-submit.js', { json: { ...err } }).body.event, 'failed');

// ── Read reply ──
const replyFor = (pred) => fixture.replies.find((r) => pred(r.comment.text));
const genuine = replyFor((t) => t.includes('date format'));
const spam = replyFor((t) => t.includes('10x'));
const readReply = (r, response) => run('8-read-reply.js', { nodes: { Settings: settings, 'Build reply request': nodeRef(r.request) }, json: response ?? r.response });
const g = readReply(genuine);
expect('genuine comment: a reply and a like', [g.reply.length > 20, g.shouldLike], [true, true]);
expect('genuine reply: no long dash, no hashtag', [/[—–]/.test(g.reply), /#\w/.test(g.reply)], [false, false]);
const sp = readReply(spam);
expect('spam: no reply, no like, a note for the author', [sp.reply, sp.shouldLike, sp.note.length > 0], ['', false, true]);
expect('a failed reply call is reported', readReply(genuine, { error: { message: 'timeout' } }).failed, true);

// ── Build post: LinkedIn's "little text" escaping ──
const RESERVED = new Set('|{}@[]()<>#\\*_~');
const firstUnescaped = (t) => {
  const s = t.replace(/\{hashtag\|\\#\|[A-Za-z0-9_]+\}/g, '');
  for (let i = 0; i < s.length; i++) {
    if (s[i] === '\\') { i++; continue; }
    if (RESERVED.has(s[i])) return s[i];
  }
  return null;
};
const pub = { id: 'x', format: 'ARTICLE', me: 'urn:li:person:abc', title: 'T', excerpt: 'E', articleUrl: 'https://example.com/writing/t', coverUrl: 'https://example.com/c.png', siteUrl: 'https://example.com' };
const buildPost = (text, upload = { statusCode: 201 }, start = { value: { image: 'urn:li:image:1', uploadUrl: 'https://u' } }) =>
  run('14-build-post.js', { nodes: { 'Build image upload': nodeRef({ ...pub, text }), 'Start image upload': nodeRef(start) }, json: upload });
const tricky = 'Data (and AI) needs owners: @team, [notes], <tags>, a_b, *stars*, ~tilde~ and a | pipe. C# too.\n\n#AIGovernance #DataQuality';
const built = buildPost(tricky);
expect('every reserved character is escaped', firstUnescaped(built.postBody.commentary), null);
expect('hashtags become hashtag templates', built.postBody.commentary.endsWith('{hashtag|\\#|AIGovernance} {hashtag|\\#|DataQuality}'), true);
expect('the real article post passes the escaping check', firstUnescaped(buildPost(art.draft.linkedinText.replace('{{LINK}}', 'https://example.com/writing/x')).postBody.commentary), null);
expect('article goes out as a link card with the cover as thumbnail', [built.postBody.content.article.source, built.postBody.content.article.thumbnail], [pub.articleUrl, 'urn:li:image:1']);
expect('a failed cover upload stops the post', [buildPost('x', { error: { message: 'boom' } }).ready, buildPost('x', { error: { message: 'boom' } }).report.event], [false, 'publish_failed']);
expect('no upload URL stops the post', buildPost('x', { statusCode: 201 }, { error: { message: '403' } }).ready, false);

// ── Read post / like results ──
const readPost = (r) => run('15-read-post-result.js', { nodes: { 'Build post': nodeRef({ id: 'x' }) }, json: r }).report;
expect('201 + x-restli-id: published with the post link', readPost({ statusCode: 201, headers: { 'x-restli-id': 'urn:li:share:9' } }), { event: 'published', linkedinUrn: 'urn:li:share:9', linkedinUrl: 'https://www.linkedin.com/feed/update/urn:li:share:9/' });
expect('422: reported as failed with the reason', readPost({ statusCode: 422, body: { message: 'bad text' } }).event, 'publish_failed');
const readLike = (r) => run('19-read-like-result.js', { nodes: { 'Build like': nodeRef({ id: 'x' }) }, json: r }).report.event;
expect('like: 201 and 409 (already liked) both count as done', [readLike({ statusCode: 201 }), readLike({ statusCode: 409 }), readLike({ statusCode: 403 })], ['liked', 'liked', 'failed']);

// ── Collect comments ──
const collected = run('20-collect-comments.js', { nodes: { 'Who am I': nodeRef(fixture.comments.who) }, input: fixture.comments.responses });
const comments = collected[0].comments;
expect('own comments are skipped (3 of 4 per post kept)', comments.length, fixture.comments.responses.length * 3);
expect('names come from the profile projection', comments.some((c) => c.authorName === 'Rudo Moyo'), true);
const withReply = clone(fixture.comments.responses);
withReply[0].elements.push({ ...withReply[0].elements[0], commentUrn: 'urn:li:comment:(x,1)', parentComment: withReply[0].elements[0].commentUrn });
expect('replies (nested comments) are not treated as new comments', run('20-collect-comments.js', { nodes: { 'Who am I': nodeRef(fixture.comments.who) }, input: withReply })[0].comments.length, comments.length);

// ── Split work ──
const jobs = { generate: [{ id: 'g' }], drafts: [], publish: [{ id: 'p' }], replies: [{ id: 'r' }], likes: [], watch: [{ id: 'w', linkedinUrn: 'u' }], siteUrl: 'https://example.com' };
const split = (who) => run('0-split-work.js', { nodes: { Settings: nodeRef({ readComments: false }), 'Check in': nodeRef(jobs), ...(who ? { 'Who am I': nodeRef(who) } : {}) } }).map((x) => x.kind);
expect('with LinkedIn identity: drafting and LinkedIn work (no comment reading when off)', split({ sub: 'abc' }), ['generate', 'publish', 'reply']);
expect('LinkedIn identity failed: only drafting runs; LinkedIn work waits for the next run', split({ error: { message: '401' } }), ['generate']);

console.log(failed ? `\n${failed} test(s) failed` : '\nAll guardrail tests passed');
process.exit(failed ? 1 : 0);
