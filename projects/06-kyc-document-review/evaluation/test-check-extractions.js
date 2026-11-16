// Offline tests for the extraction guardrail ("Check extractions"), using real Claude responses.
//
// Runs workflows/code/7-check-extractions.js against evaluation/fixture-live-c01.json: the digital text and
// the actual Claude responses for a specimen passport photo and a specimen electricity bill. No API call.
//
//   node evaluation/test-check-extractions.js

const fs = require('fs');
const path = require('path');

const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixture-live-c01.json'), 'utf8'));
const code = fs.readFileSync(path.join(__dirname, '..', 'workflows/code/7-check-extractions.js'), 'utf8');
const node = (json, all) => ({ first: () => ({ json }), all: () => all || [{ json }], isExecuted: true });
const run = (responses) => new Function('$', '$input', code)(
  (name) => ({ Settings: node(fixture.settings), 'Get page images': node(null, fixture.inputs.map((json) => ({ json }))) }[name]),
  node(null, responses.map((json) => ({ json }))),
)[0].json;

const clone = (x) => JSON.parse(JSON.stringify(x));
const idx = (name) => fixture.inputs.findIndex((i) => i.filename === name);
const P = idx('passport.jpg');
const B = idx('electricity_bill.pdf');
const withAnswer = (i, mutate) => fixture.responses.map((r, j) => {
  if (j !== i) return r;
  const c = clone(r); const a = JSON.parse(c.content.find((b) => b.type === 'text').text); mutate(a);
  c.content = [{ type: 'text', text: JSON.stringify(a) }];
  return c;
});
const of = (out, i) => out.extractions.find((e) => e.document_id === fixture.inputs[i].document_id);

let failed = 0;
const expect = (name, got, want) => {
  const pass = JSON.stringify(got) === JSON.stringify(want);
  if (!pass) failed++;
  console.log(`${pass ? 'PASS' : 'FAIL'}  ${name}${pass ? '' : `  (got ${JSON.stringify(got)}, expected ${JSON.stringify(want)})`}`);
};

const real = run(fixture.responses);
expect('real responses: both documents stored', real.extractions.length, 2);
expect('real responses: nothing unverified on the digital bill', of(real, B).verification.unverified, []);
expect('real responses: the bill was checked against its own text', of(real, B).verification.digital_text_checked, true);
expect('"" from the model becomes null (passport has no bill date)', of(real, P).fields.document_date.value, null);
expect('the passport MRZ line 2 is kept exactly (44 characters)', (of(real, P).fields.mrz_line2.value || '').length, 44);

const badDate = run(withAnswer(P, (a) => { a.fields.expiry_date.value = '2030-02-30'; }));
expect('an impossible date is dropped and reported', [of(badDate, P).fields.expiry_date.value, of(badDate, P).verification.unverified.some((u) => u.includes('expiry_date'))], [null, true]);

const otherName = run(withAnswer(B, (a) => { a.fields.full_name.as_printed = 'Chipo Marufu'; a.fields.full_name.value = 'Chipo Marufu'; }));
expect('a name not in the bill\'s own text is marked unverified', of(otherName, B).verification.unverified.some((u) => u.includes('Chipo Marufu')), true);

const failedCall = run(fixture.responses.map((r, j) => (j === B ? { error: { message: 'overloaded' } } : r)));
expect('a failed call stores nothing for that document (it stays unread)', [failedCall.extractions.length, failedCall.calls, !!of(failedCall, B)], [1, 2, false]);
expect('a failed call is reported', failedCall.problems.some((p) => p.includes('electricity_bill.pdf')), true);

const cutOff = run(fixture.responses.map((r, j) => (j === P ? { ...clone(r), stop_reason: 'max_tokens' } : r)));
expect('a cut-off answer stores nothing, but its tokens are still costed', [!!of(cutOff, P), cutOff.cost_usd > of(cutOff, B).cost_usd], [false, true]);

const refusal = run(fixture.responses.map((r, j) => (j === P ? { ...clone(r), stop_reason: 'refusal' } : r)));
expect('a refusal stores nothing', !!of(refusal, P), false);

console.log(failed ? `\n${failed} test(s) failed` : '\nAll guardrail tests passed');
process.exit(failed ? 1 : 0);
