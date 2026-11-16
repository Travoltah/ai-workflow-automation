// Offline tests for the brief guardrail ("Verify briefs"), using real Claude responses.
//
// Runs workflows/code/6-verify-briefs.js against evaluation/fixture-live-run-2.json: the inputs and
// the six actual Claude Opus briefs from live run #2 (fictional regulators). No n8n, no API call, no cost.
//
//   node evaluation/test-verify-briefs.js
//
// Why it exists: in live run #2, one brief (the AU automated-decisions guidance) had a good summary but
// no obligations, no controls and no relevance, and it passed every accuracy check. The completeness check
// was added for that; these tests replay the real answer and also try every kind of fabrication.

const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixture-live-run-2.json'), 'utf8'));
const verifyCode = fs.readFileSync(path.join(root, 'workflows/code/6-verify-briefs.js'), 'utf8');

const node = (json, all) => ({ first: () => ({ json }), all: () => all || [{ json }], isExecuted: true });
const run = (responses) => new Function('$', '$input', verifyCode)(
  (name) => ({ 'Load changes': node(fixture.loadChanges), 'One item per brief': node(null, fixture.requests.map((json) => ({ json }))) }[name]),
  node(null, responses.map((json) => ({ json }))),
)[0].json.briefs;

const clone = (x) => JSON.parse(JSON.stringify(x));
const answer = (r) => JSON.parse(r.content.find((b) => b.type === 'text').text);
const withAnswer = (i, mutate) => fixture.responses.map((r, j) => {
  if (j !== i) return r;
  const c = clone(r); const a = answer(c); mutate(a);
  c.content = [{ type: 'text', text: JSON.stringify(a) }];
  return c;
});
const titleOf = (b) => fixture.loadChanges.data.changes.find((c) => c.change_id === b.change_id);
const idx = (jurisdiction, word) => fixture.requests.findIndex((r) => {
  const c = fixture.loadChanges.data.changes.find((x) => x.change_id === r.change_id);
  return c.jurisdiction === jurisdiction && c.title.includes(word);
});

let failed = 0;
const expect = (name, got, want) => {
  const pass = JSON.stringify(got) === JSON.stringify(want);
  if (!pass) failed++;
  console.log(`${pass ? 'PASS' : 'FAIL'}  ${name}${pass ? '' : `  (got ${JSON.stringify(got)}, expected ${JSON.stringify(want)})`}`);
};

const real = run(fixture.responses);
const au = real.find((b) => titleOf(b).jurisdiction === 'AU');
expect('real run: the incomplete AU brief is flagged', au.status, 'flagged');
expect('real run: flagged because it is incomplete', au.verification.removed.some((r) => r.startsWith('incomplete')), true);
expect('real run: the other 5 briefs pass every check', real.filter((b) => b !== au && b.status === 'analysed').length, 5);

const eu = idx('EU', 'breach');
const tamperedQuote = run(withAnswer(eu, (a) => { a.obligations[0].quote = a.obligations[0].quote.replace('48 hours', '24 hours'); }));
expect('a quote changed by one word is removed and the brief flagged', [tamperedQuote[eu].status, tamperedQuote[eu].verification.removed.some((r) => r.includes('quote not found'))], ['flagged', true]);

const wrongDay = run(withAnswer(eu, (a) => { a.key_dates = [{ date: '2027-03-15', type: 'effective', quote: 'From 1 March 2027' }]; }));
expect('a date its quote does not state is removed', wrongDay[eu].verification.removed.some((r) => r.includes('2027-03-15')), true);

const impossible = run(withAnswer(eu, (a) => { a.key_dates = [{ date: '2027-02-30', type: 'effective', quote: 'From 1 March 2027' }]; }));
expect('an impossible date (30 February) is removed', impossible[eu].verification.removed.some((r) => r.includes('not a real calendar date')), true);

const invented = run(withAnswer(eu, (a) => { a.affected_controls.push({ control_id: 'AI-MAGIC', why: 'invented' }); }));
expect('a control that is not in the library is removed', [invented[eu].brief.affected_controls.some((c) => c.control_id === 'AI-MAGIC'), invented[eu].status], [false, 'flagged']);

const tolerant = run(withAnswer(eu, (a) => { a.obligations[0].quote = a.obligations[0].quote.replace(' ', '   ').replace(/'/g, '’').toUpperCase(); }));
expect('extra spaces, curly quotes and case do not cause a false rejection', tolerant[eu].status, 'analysed');

const errored = run(fixture.responses.map((r, j) => (j === eu ? { error: { message: 'overloaded' } } : r)));
expect('a failed call gets a fallback brief, flagged', [errored[eu].status, errored[eu].brief.summary.startsWith('Not analysed')], ['flagged', true]);

const byJ = Object.fromEntries(real.map((b) => [titleOf(b).jurisdiction + ':' + titleOf(b).title.slice(0, 12), [b.applicability, b.priority]]));
expect('EU (a market the company is in) is in_market / high', byJ['EU:Guidance: pe'], ['in_market', 'high']);
expect('US (a watch market) is watch_market / medium', byJ['US:Proposed rul'], ['watch_market', 'medium']);

console.log(failed ? `\n${failed} test(s) failed` : '\nAll guardrail tests passed');
process.exit(failed ? 1 : 0);
