// NODE: "Lay out test script"  (Code node, mode: Run Once for All Items)
// Puts the test cases in test-script order and numbers them:
//   sections A, B, C, ... one per story, then a final Regression section;
//   ids PREFIX-001, PREFIX-002, ... across the whole script (prefix from the form, the document, or Settings).
// Then decides the QA ticket for each story:
//   create   no QA ticket yet                      -> create one and link it to the story
//   comment  the story already has a linked "QA:" ticket -> add the new test cases as a comment
//   none     the story is not in Jira, or "Create Jira tickets" is No

const run = $('Collect inputs').first().json;
const analysed = $('Read analysis').isExecuted ? $('Read analysis').first().json : null;
const settings = run.settings;
const stories = $input.all().map((item) => item.json);
const prefix = run.testIdPrefix || analysed?.analysis.document.testIdPrefix || settings.defaultTestIdPrefix || 'TC';
const QA_PREFIX = 'QA: ';

const letters = (n) => (n < 26 ? String.fromCharCode(65 + n) : letters(Math.floor(n / 26) - 1) + String.fromCharCode(65 + (n % 26)));
const regressionLetter = letters(stories.length);
let counter = 0;
const nextId = () => `${prefix}-${String(++counter).padStart(3, '0')}`;

function details(t) {
  const parts = [`Preconditions: ${t.preconditions}`];
  if (t.testData && t.testData.trim().toLowerCase() !== 'none') parts.push(`Test data: ${t.testData}`);
  parts.push(['Steps:', ...t.steps.map((s, i) => `${i + 1}. ${s}`)].join('\n'));
  return parts.join('\n\n');
}

// Pass 1: main sections. Pass 2: the regression section. Ids follow the sheet order.
const idMap = stories.map(() => ({}));
const rows = stories.map(() => []);
stories.forEach((story, s) => {
  for (const t of story.testCases.filter((t) => t.type !== 'Regression')) {
    const id = nextId();
    idMap[s][t.id] = id;
    rows[s].push({ ...t, id, section: letters(s) });
  }
});
stories.forEach((story, s) => {
  for (const t of story.testCases.filter((t) => t.type === 'Regression')) {
    const id = nextId();
    idMap[s][t.id] = id;
    rows[s].push({ ...t, id, section: regressionLetter });
  }
});

const wiki = (value) => String(value ?? '').replace(/([{}[\]|])/g, '\\$1');
const today = new Date().toISOString().slice(0, 10);

function qaDescription(story, storyRows, heading) {
  const lines = [
    heading,
    '',
    `Test cases for [${story.jiraKey}|${story.jiraUrl}]: ${wiki(story.title)}`,
    `Run them from the Excel test script for ${wiki(analysed?.analysis.document.changeRequest || story.title)}, `
      + `section ${letters(stories.indexOf(story))}. Record PASS / FAIL / BLOCKED there.`,
    '',
    'h3. Acceptance criteria',
    ...story.acceptanceCriteria.map((ac) => `# ${wiki(ac.text)} _(${ac.source})_`),
    '',
    'h3. Test cases',
    '||ID||Type||Scenario||Priority||Covers||',
    ...storyRows.map((r) => `|${r.id}|${r.type}|${wiki(r.scenario)}|${r.priority}|${r.covers.join(', ')}|`),
  ];
  for (const r of storyRows) {
    lines.push('', `h4. ${r.id} ${wiki(r.scenario)}`, `*Preconditions:* ${wiki(r.preconditions)}`);
    if (r.testData && r.testData.toLowerCase() !== 'none') lines.push(`*Test data:* ${wiki(r.testData)}`);
    lines.push('*Steps:*', ...r.steps.map((step) => `# ${wiki(step)}`), `*Expected:* ${wiki(r.expectedResult)}`);
  }
  if (story.clarifyingQuestions.length) {
    lines.push('', 'h3. Open questions', ...story.clarifyingQuestions.map((q) => `* ${wiki(q)}`));
  }
  const text = lines.join('\n');
  return text.length > 32000 ? `${text.slice(0, 31800)}\n\n_(Shortened: the Excel test script has every test case.)_` : text;
}

return stories.map((story, s) => {
  const storyRows = rows[s];
  const existingQa = (story.issueLinks ?? [])
    .map((link) => link.inwardIssue ?? link.outwardIssue)
    .find((issue) => issue?.fields?.summary?.startsWith(QA_PREFIX));
  const canUseJira = run.createInJira && story.jiraKey && storyRows.length > 0;
  const qaAction = !canUseJira ? 'none' : existingQa ? 'comment' : 'create';
  const isSubtask = /sub-?task/i.test(settings.qaIssueType);

  return {
    json: {
      ...story,
      section: letters(s),
      regressionSection: regressionLetter,
      testIdPrefix: prefix,
      rows: storyRows.map((r) => ({ ...r, covers: r.covers, details: details(r) })),
      qaAction,
      qaKey: existingQa?.key ?? '',
      qaUrl: existingQa ? `${settings.jiraBaseUrl}/browse/${existingQa.key}` : '',
      qaCreateBody: qaAction !== 'create' ? null : {
        fields: {
          project: { key: story.jiraKey.split('-')[0] },
          issuetype: { name: settings.qaIssueType },
          summary: `${QA_PREFIX}${story.title}`.slice(0, 250),
          description: qaDescription(story, storyRows, `_Created by the Requirements-to-Test-Script workflow on ${today}._`),
          labels: ['ai-qa-tests'],
          ...(isSubtask ? { parent: { key: story.jiraKey } } : {}),
        },
      },
      qaCommentBody: qaAction !== 'comment' ? null : {
        body: qaDescription(story, storyRows, `h3. Test cases regenerated on ${today}`),
      },
    },
  };
});
