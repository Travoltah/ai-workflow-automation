// NODE: "Normalize story"  (Code node, mode: Run Once for All Items)
// Turns every kind of input (a Jira issue, the web form, an API call) into one clean
// "story" shape, so the rest of the workflow never has to care where the story came from.

// Optional: if your Jira project keeps acceptance criteria in a custom field, put its id
// here (for example 'customfield_10045'). Otherwise they are read from the description,
// under a heading such as "Acceptance criteria".
const AC_CUSTOM_FIELD = '';

// Which trigger started this run? Used later to reply in the right place.
const channel = $('Generate from form').isExecuted
  ? 'form'
  : $('Generate via API').isExecuted
    ? 'api'
    : 'schedule';

// Jira Cloud can return descriptions as Atlassian Document Format (a JSON tree).
// This flattens it to plain text, keeping list items on their own lines.
function adfToText(node) {
  if (!node) return '';
  if (node.type === 'text') return node.text ?? '';
  if (node.type === 'hardBreak') return '\n';
  const inner = (node.content ?? []).map(adfToText).join('');
  if (node.type === 'listItem') return `- ${inner.trim()}\n`;
  if (['paragraph', 'heading', 'bulletList', 'orderedList', 'codeBlock'].includes(node.type)) return `${inner}\n`;
  return inner;
}

function toText(value) {
  if (value === undefined || value === null) return '';
  if (typeof value === 'string') return value.trim();
  if (typeof value === 'object' && value.type === 'doc') return adfToText(value).trim();
  return String(value).trim();
}

// Accepts an array, or text with one criterion per line. Strips bullets, numbering and "AC1:" prefixes.
function splitCriteria(value) {
  if (Array.isArray(value)) return value.flatMap(splitCriteria);
  return toText(value)
    .split(/\r?\n/)
    .map((line) => line.replace(/^\s*(?:[-*•#]+|\d+[.)]|AC\s*\d+\s*[:.)-]?)\s*/i, '').trim())
    .filter(Boolean);
}

// Finds an "Acceptance criteria" section in a description (Markdown, Jira wiki or plain text).
function extractCriteria(text) {
  const match = text.match(/(?:^|\n)[ \t]*(?:h\d\.[ \t]*|#+[ \t]*|\*+)?acceptance criteria\*?[ \t]*:?[ \t]*\*?[ \t]*\n/i);
  if (!match) return { description: text, criteria: [] };
  return {
    description: text.slice(0, match.index).trim(),
    criteria: splitCriteria(text.slice(match.index + match[0].length)),
  };
}

return $input.all().map((item, index) => {
  const input = item.json;
  let story;

  if (input.fields) {
    // A Jira issue (from "Get Jira story" or "Find stories labelled for test design")
    const f = input.fields;
    const parsed = extractCriteria(toText(f.description));
    const custom = AC_CUSTOM_FIELD ? splitCriteria(f[AC_CUSTOM_FIELD]) : [];
    story = {
      issueKey: input.key,
      summary: toText(f.summary),
      description: parsed.description,
      criteria: custom.length ? custom : parsed.criteria,
      issueType: f.issuetype?.name ?? '',
      labels: f.labels ?? [],
      components: (f.components ?? []).map((c) => c.name),
      fromJira: true,
    };
  } else {
    // A story typed into the form or sent to the API
    const parsed = extractCriteria(toText(input.description));
    const given = splitCriteria(input.acceptanceCriteria);
    story = {
      issueKey: '',
      summary: toText(input.summary),
      description: parsed.description,
      criteria: given.length ? given : parsed.criteria,
      issueType: 'Story',
      labels: [],
      components: [],
      fromJira: false,
    };
  }

  if (!story.summary && !story.description && !story.criteria.length) {
    throw new Error('The story is empty. Enter a Jira issue key, or a title, description or acceptance criteria.');
  }

  const { criteria, ...rest } = story;
  return {
    json: {
      ...rest,
      acceptanceCriteria: criteria.map((text, n) => ({ id: `AC${n + 1}`, text })),
      channel,
      receivedAt: new Date().toISOString(),
    },
    pairedItem: { item: index },
  };
});
