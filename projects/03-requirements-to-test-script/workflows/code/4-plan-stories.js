// NODE: "Plan stories"  (Code node, mode: Run Once for All Items)
// Decides, story by story, what happens in Jira:
//   create   a story found in the document, not yet in Jira          -> create a Jira story
//   reuse    a story from this document that an earlier run created  -> keep it, never recreate
//   fetch    a Jira key the user typed                               -> read it from Jira, never recreate
//   preview  "Create Jira tickets" is No                             -> no Jira at all
// Output: one item per story.

const run = $('Collect inputs').first().json;
const analysed = $('Read analysis').isExecuted ? $('Read analysis').first().json : null;
const searched = $('Find stories from earlier runs').isExecuted ? $('Find stories from earlier runs').first().json : null;
if (searched?.error) {
  throw new Error(`Could not search Jira for stories from earlier runs: ${JSON.stringify(searched.error).slice(0, 300)}`);
}

// Which new story is which earlier story? Claude's answer from "Match earlier stories", checked
// here: only keys that really exist, each used once. Without it, fall back to identical titles.
const earlier = searched?.issues ?? [];
const byKey = new Map(earlier.map((issue) => [issue.key, issue]));
const normalise = (title) => String(title ?? '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
const byTitle = new Map(earlier.map((issue) => [normalise(issue.fields.summary), issue]));
const matchedKey = {};
if ($('Match earlier stories').isExecuted) {
  const response = $('Match earlier stories').first().json;
  try {
    const text = (response.content ?? []).filter((b) => b.type === 'text').map((b) => b.text).join('');
    const used = new Set();
    for (const m of JSON.parse(text).matches) {
      if (byKey.has(m.existingKey) && !used.has(m.existingKey)) {
        matchedKey[m.ref] = m.existingKey;
        used.add(m.existingKey);
      }
    }
  } catch (error) {
    // Matching failed: identical titles are still recognised below.
  }
}
const findEarlier = (story) => byKey.get(matchedKey[story.ref]) ?? byTitle.get(normalise(story.title));
const browse = (key) => `${run.settings.jiraBaseUrl}/browse/${key}`;

// Jira wiki markup. The acceptance criteria come last, so a later run that reads this
// story back (as an existing Jira key) finds them under the heading.
const wiki = (value) => String(value ?? '').replace(/([{}[\]])/g, '\\$1');
function storyDescription(story, document) {
  const lines = [
    `_Created by the Requirements-to-Test-Script workflow from ${wiki(document.changeRequest || document.title)}._`,
    '',
    `*${wiki(story.userStory)}*`,
    '',
    wiki(story.description),
  ];
  if (story.sourceRefs.length) lines.push('', 'h3. Source', story.sourceRefs.map((ref) => `* ${wiki(ref)}`).join('\n'));
  if (story.wireframeNotes) lines.push('', 'h3. Wireframes', wiki(story.wireframeNotes));
  const generated = story.acceptanceCriteria.some((ac) => ac.source === 'generated');
  if (generated) lines.push('', '_Criteria marked (generated) were written by AI because the document did not state them. Please review._');
  lines.push('', 'h3. Acceptance criteria',
    story.acceptanceCriteria.map((ac) => `# ${wiki(ac.text)}${ac.source === 'generated' ? ' _(generated)_' : ''}`).join('\n'));
  return lines.join('\n').slice(0, 32000);
}

const items = [];
const analysis = analysed?.analysis;
const typedKeys = new Set(run.jiraKeys);
const reusedKeys = new Set();

for (const story of analysis?.stories ?? []) {
  const found = findEarlier(story);
  const match = found && !reusedKeys.has(found.key) ? found : null;
  if (match) reusedKeys.add(match.key);
  const action = !run.createInJira ? 'preview' : match ? 'reuse' : 'create';
  if (match && typedKeys.has(match.key)) continue; // the user typed it too: read it once, as "fetch"
  items.push({
    action,
    origin: { create: 'Created from document', reuse: 'Already in Jira (earlier run)', preview: 'Preview (not in Jira)' }[action],
    ref: story.ref,
    jiraKey: match?.key ?? '',
    jiraUrl: match ? browse(match.key) : '',
    projectKey: run.projectKey,
    module: story.module,
    shortName: story.shortName,
    title: story.title,
    userStory: story.userStory,
    description: story.description,
    acceptanceCriteria: story.acceptanceCriteria,
    sourceRefs: story.sourceRefs,
    wireframeNotes: story.wireframeNotes,
    priority: story.priority,
    issueLinks: match?.fields?.issuelinks ?? [],
    labels: ['ai-generated-story', analysed.crLabel],
    jiraCreateBody: action !== 'create' ? null : {
      fields: {
        project: { key: run.projectKey },
        issuetype: { name: run.settings.storyIssueType },
        summary: story.title.slice(0, 250),
        description: storyDescription(story, analysis.document),
        labels: ['ai-generated-story', analysed.crLabel],
      },
    },
  });
}

for (const key of run.jiraKeys) {
  items.push({
    action: 'fetch', origin: 'Existing Jira story', ref: key, jiraKey: key, jiraUrl: browse(key),
    projectKey: key.split('-')[0],
  });
}

if (!items.length) throw new Error('No stories to test.');
return items.map((json, seq) => ({ json: { seq, ...json } }));
