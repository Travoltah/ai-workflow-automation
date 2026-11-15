// NODE: "Read analysis"  (Code node, mode: Run Once for Each Item)
// Checks Claude's breakdown of the document before any Jira ticket is created.

const request = $('Build analysis request').item.json;
const response = $json;
const run = $('Collect inputs').item.json;

const text = (response.content ?? []).filter((b) => b.type === 'text').map((b) => b.text).join('');
if (response.stop_reason === 'refusal') throw new Error('Claude declined to analyse these documents (stop_reason: refusal).');
if (response.stop_reason === 'max_tokens') {
  throw new Error('The analysis was cut off. Raise MAX_TOKENS in "Build analysis request", or split the document.');
}
let analysis;
try {
  analysis = JSON.parse(text);
} catch (error) {
  throw new Error('The analysis was not valid JSON.');
}
if (analysis.status !== 'ok' || !analysis.stories.length) {
  if (!run.jiraKeys.length) throw new Error(`No user stories found in the documents: ${analysis.statusReason}`);
}

const issues = [];
const refs = analysis.stories.map((s) => s.ref);
if (new Set(refs).size !== refs.length) issues.push('Duplicate story references.');
for (const s of analysis.stories) {
  if (!s.acceptanceCriteria.length) issues.push(`${s.ref} has no acceptance criteria.`);
  const ids = s.acceptanceCriteria.map((ac) => ac.id);
  if (new Set(ids).size !== ids.length) issues.push(`${s.ref} has duplicate criterion ids.`);
}

const prefix = (analysis.document.testIdPrefix || '').toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 5);

// Every Jira story created from this document gets this label. A second run on the same
// document finds those stories through it and reuses them instead of creating duplicates.
const reference = analysis.document.changeRequest || analysis.document.title || 'requirements';
const crLabel = 'req2test-' + reference.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 60);

return {
  json: {
    crLabel,
    analysis: {
      ...analysis,
      document: { ...analysis.document, testIdPrefix: prefix },
    },
    analysisIssues: issues,
    analysisUsage: response.usage ?? {},
    analysisSeconds: Math.round((Date.now() - request.startedAt) / 1000),
  },
};
