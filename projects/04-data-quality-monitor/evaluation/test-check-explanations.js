// Offline tests for the AI guardrail ("Check explanations"), using a real Claude response.
//
// Runs the workflow's own Code-node files (workflows/code/1-plan-explanations.js and
// 2-check-explanations.js) against evaluation/fixture-live-run-4.json: the inputs and the actual
// Claude response from live run #4. No n8n, no API call, no cost.
//
//   node evaluation/test-check-explanations.js
//
// Why it exists: in live run #4 the check rejected 2 of 16 explanations because Claude cited ids
// quoted in a row's detail text ("used by customers 1854, 2108") rather than the record_id itself.
// Those ids were real, so the check was too strict. The fix accepts any id Claude was shown, and
// these tests prove that invented ids, bad rule links and broken answers are still rejected.

const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const read = (f) => fs.readFileSync(path.join(root, f), 'utf8');
const fixture = JSON.parse(read('evaluation/fixture-live-run-4.json'));
const planCode = read('workflows/code/1-plan-explanations.js');
const checkCode = read('workflows/code/2-check-explanations.js');

// Minimal stand-ins for n8n's $() and $input.
const node = (json) => ({ first: () => ({ json }), all: () => [{ json }], isExecuted: true });
const runCode = (code, nodes, input) => new Function('$', '$input', code)((name) => nodes[name], node(input));

const settings = { model: fixture.settings.model };
const plan = runCode(planCode, { Settings: node(settings) }, { result: fixture.plan.result })[0].json;
const check = (response, planOverride = plan) =>
  runCode(checkCode, { 'Plan explanations': node(planOverride), Settings: node(settings) }, response)[0].json;

const clone = (x) => JSON.parse(JSON.stringify(x));
const answerOf = (r) => JSON.parse(r.content.find((b) => b.type === 'text').text);
const withAnswer = (mutate) => {
  const r = clone(fixture.claudeResponse);
  const a = answerOf(r);
  mutate(a);
  r.content = [{ type: 'text', text: JSON.stringify(a) }];
  return r;
};
const okCount = (out) => out.explanations.filter((e) => e.explanation_ok).length;
const total = plan.result.actions.filter((a) => a.action === 'new').length;

let failed = 0;
const expect = (name, got, want) => {
  const pass = JSON.stringify(got) === JSON.stringify(want);
  if (!pass) failed++;
  console.log(`${pass ? 'PASS' : 'FAIL'}  ${name}${pass ? '' : `  (got ${JSON.stringify(got)}, expected ${JSON.stringify(want)})`}`);
};

// 1. The bug, reproduced: the old check only knew the record_id values.
const oldPlan = { ...plan, sentSamples: Object.fromEntries(Object.entries(fixture.plan.sentSamples)) };
expect('old check rejects the 2 real-but-quoted evidence ids (bug reproduced)', okCount(check(fixture.claudeResponse, oldPlan)), total - 2);

// 2. The fix: the real response passes in full.
const real = check(fixture.claudeResponse);
expect(`real Claude response from live run #4: ${total}/${total} explanations pass`, okCount(real), total);

// 3. An invented record id is still rejected, and only for that incident.
const invented = check(withAnswer((a) => a.incidents[0].evidence_ids.push('9999999')));
expect('an invented evidence id is rejected', okCount(invented), total - 1);
expect('the rejected incident gets the fallback note', invented.explanations.find((e) => !e.explanation_ok)?.explanation.likely_cause.startsWith('Not explained'), true);

// 4. A link to a rule that did not fail is rejected.
expect('a related rule that did not fail is rejected', okCount(check(withAnswer((a) => a.incidents[1].related_rules.push('NOT_A_RULE')))), total - 1);

// 5. A missing explanation falls back; an extra one for an unknown rule is reported.
const missing = check(withAnswer((a) => { a.incidents.pop(); a.incidents.push({ ...a.incidents[0], rule_code: 'MADE_UP_RULE' }); }));
expect('a missing explanation falls back', okCount(missing), total - 1);
expect('an explanation for a rule that did not fail is reported', missing.problems.some((p) => p.includes('MADE_UP_RULE')), true);

// 6. Refusals, cut-off answers and API errors never reach Jira as explanations.
expect('a refusal falls back for every incident', okCount(check({ ...clone(fixture.claudeResponse), stop_reason: 'refusal' })), 0);
expect('a cut-off answer falls back for every incident', okCount(check({ ...clone(fixture.claudeResponse), stop_reason: 'max_tokens' })), 0);
expect('an API error falls back for every incident', okCount(check({ error: { message: 'overloaded' } })), 0);

console.log(failed ? `\n${failed} test(s) failed` : '\nAll guardrail tests passed');
process.exit(failed ? 1 : 0);
