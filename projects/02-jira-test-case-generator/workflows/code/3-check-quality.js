// NODE: "Check quality"  (Code node, mode: Run Once for Each Item)
// Reads Claude's answer and checks it like a QA lead would, before anything is saved or
// posted to Jira: every acceptance criterion covered, no broken references, no duplicates,
// no empty steps, and at least one negative test. The result is a pass/fail quality gate.

const story = $('Build Claude request').item.json;
const response = $json;
const issues = [];

// 1. Read the answer
const text = (response.content ?? [])
  .filter((block) => block.type === 'text')
  .map((block) => block.text)
  .join('');

if (response.stop_reason === 'refusal') issues.push('Claude declined this request (stop_reason: refusal).');
if (response.stop_reason === 'max_tokens') issues.push('The answer was cut off. Raise MAX_TOKENS or split the story.');

let result = null;
try {
  result = JSON.parse(text);
} catch (error) {
  issues.push('The answer was not valid JSON.');
}
result = result ?? {
  status: 'error',
  statusReason: issues.join(' '),
  acceptanceCriteria: [],
  testCases: [],
  assumptions: [],
  clarifyingQuestions: [],
};

// 2. Quality checks
const criteria = result.acceptanceCriteria;
const tests = result.testCases;
const criterionIds = criteria.map((ac) => ac.id);
const coveredIds = new Set(tests.flatMap((t) => t.covers));
const uncovered = criterionIds.filter((id) => !coveredIds.has(id));
const unknownRefs = [...coveredIds].filter((id) => !criterionIds.includes(id));
const droppedGiven = story.acceptanceCriteria.map((ac) => ac.id).filter((id) => !criterionIds.includes(id));
const duplicates = (values) => values.filter((v, i) => values.indexOf(v) !== i);
const typeMix = tests.reduce((mix, t) => ({ ...mix, [t.type]: (mix[t.type] ?? 0) + 1 }), {});

if (result.status === 'ok') {
  if (!tests.length) issues.push('Status is ok but there are no test cases.');
  if (uncovered.length) issues.push(`Acceptance criteria without a test: ${uncovered.join(', ')}.`);
  if (droppedGiven.length) issues.push(`Given acceptance criteria missing from the answer: ${droppedGiven.join(', ')}.`);
  if (unknownRefs.length) issues.push(`Tests refer to unknown criteria: ${unknownRefs.join(', ')}.`);
  if (!typeMix.negative) issues.push('No negative test case.');
  if (duplicates(tests.map((t) => t.id)).length) issues.push('Duplicate test case ids.');
  if (duplicates(tests.map((t) => t.title.trim().toLowerCase())).length) issues.push('Duplicate test case titles.');
  const incomplete = tests.filter((t) => !t.steps.length || !t.expectedResult.trim()).map((t) => t.id);
  if (incomplete.length) issues.push(`Tests without steps or an expected result: ${incomplete.join(', ')}.`);
} else if (result.status === 'needs_clarification' && !result.clarifyingQuestions.length) {
  issues.push('Clarification requested but no questions were asked.');
}

const coveragePct = criterionIds.length
  ? Math.round(((criterionIds.length - uncovered.length) / criterionIds.length) * 100)
  : 0;

return {
  json: {
    issueKey: story.issueKey,
    summary: story.summary,
    labels: story.labels,
    channel: story.channel,
    fromJira: story.fromJira,
    model: story.model,
    ...result,
    quality: {
      passed: result.status !== 'error' && issues.length === 0,
      issues,
      coveragePct,
      criteriaCount: criterionIds.length,
      testCount: tests.length,
      uncovered,
      typeMix,
      automationCandidates: tests.filter((t) => t.automationCandidate).length,
    },
    usage: {
      inputTokens: response.usage?.input_tokens ?? null,
      outputTokens: response.usage?.output_tokens ?? null,
    },
    latencyMs: Date.now() - story.startedAt,
  },
};
