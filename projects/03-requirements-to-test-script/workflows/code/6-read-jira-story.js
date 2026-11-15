// NODE: "Read Jira story"  (Code node, mode: Run Once for Each Item)
// Runs after "Get Jira story": turns an existing Jira story into the same shape as a story
// from the document. Acceptance criteria are read from the description (a heading such as
// "Acceptance criteria"), or from a custom field. Stories without any get criteria written
// by Claude in the next step.

// Optional: if your Jira keeps acceptance criteria in a custom field, put its id here,
// for example 'customfield_10045'.
const AC_CUSTOM_FIELD = '';

const planned = $('Plan stories').item.json;
const error = $json.error;
if (error) {
  const message = typeof error === 'string' ? error : [error.message, error.description].filter(Boolean).join(': ');
  return { json: { ...planned, origin: 'Could not read from Jira', jiraError: `${planned.jiraKey}: ${message}`.slice(0, 500) } };
}

// Jira Cloud may return Atlassian Document Format (a JSON tree) instead of text.
function adfToText(node) {
  if (!node) return '';
  if (node.type === 'text') return node.text ?? '';
  if (node.type === 'hardBreak') return '\n';
  const inner = (node.content ?? []).map(adfToText).join('');
  if (node.type === 'listItem') return `- ${inner.trim()}\n`;
  if (['paragraph', 'heading', 'bulletList', 'orderedList', 'codeBlock'].includes(node.type)) return `${inner}\n`;
  return inner;
}
const toText = (value) => (value == null ? '' : typeof value === 'object' && value.type === 'doc' ? adfToText(value) : String(value)).trim();

function splitCriteria(value) {
  if (Array.isArray(value)) return value.flatMap(splitCriteria);
  return toText(value)
    .split(/\r?\n/)
    .map((line) => line.replace(/^\s*(?:[-*•#]+|\d+[.)]|AC\s*\d+\s*[:.)-]?)\s*/i, '').replace(/\s*_\(generated\)_\s*$/, '').trim())
    .filter(Boolean);
}
function extractCriteria(text) {
  const match = text.match(/(?:^|\n)[ \t]*(?:h\d\.[ \t]*|#+[ \t]*|\*+)?acceptance criteria\*?[ \t]*:?[ \t]*\*?[ \t]*\n/i);
  if (!match) return { description: text, criteria: [] };
  return { description: text.slice(0, match.index).trim(), criteria: splitCriteria(text.slice(match.index + match[0].length)) };
}

const f = $json.fields ?? {};
const parsed = extractCriteria(toText(f.description));
const custom = AC_CUSTOM_FIELD ? splitCriteria(f[AC_CUSTOM_FIELD]) : [];
const criteria = custom.length ? custom : parsed.criteria;
const components = (f.components ?? []).map((c) => c.name);

return {
  json: {
    ...planned,
    jiraKey: $json.key ?? planned.jiraKey,
    title: toText(f.summary),
    issueType: f.issuetype?.name ?? '',
    status: f.status?.name ?? '',
    module: components[0] ?? '',
    shortName: '',
    userStory: '',
    description: parsed.description,
    acceptanceCriteria: criteria.map((text, n) => ({ id: `AC${n + 1}`, text, source: 'jira' })),
    sourceRefs: [],
    wireframeNotes: '',
    priority: f.priority?.name ?? '',
    labels: f.labels ?? [],
    issueLinks: f.issuelinks ?? [],
    jiraError: '',
  },
};
