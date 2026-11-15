// NODE: "Collect results"  (Code node, mode: Run Once for All Items)
// Builds the content of the Excel test script and the summary shown to the user.

// Opus 5.5 list prices per million tokens, for the cost estimate. Change if you switch models.
const PRICE_PER_MTOK = { input: 4, output: 20 };

const run = $('Collect inputs').first().json;
const files = $('Read files').first().json;
const analysed = $('Read analysis').isExecuted ? $('Read analysis').first().json : null;
const doc = analysed?.analysis.document;
const stories = $input.all().map((item) => item.json).sort((a, b) => a.seq - b.seq);
const skipped = stories[0]?.skipped ?? [];
const regressionLetter = stories[0].regressionSection;

// ── Sheets ───────────────────────────────────────────────────────────────────
const excelRow = (story, r) => ({
  id: r.id, module: r.module, type: r.type, scenario: r.scenario, details: r.details,
  expected: r.expectedResult, priority: r.priority, covers: r.covers,
  jiraStory: story.jiraKey || story.ref, jiraStoryUrl: story.jiraUrl, qaTicket: story.qaKey, qaTicketUrl: story.qaUrl,
});
const sections = stories.map((story) => ({
  letter: story.section,
  name: story.title,
  shortName: story.sectionName,
  rows: story.rows.filter((r) => r.section === story.section).map((r) => excelRow(story, r)),
}));
sections.push({
  letter: regressionLetter, name: 'Regression', shortName: 'Regression',
  rows: stories.flatMap((story) => story.rows.filter((r) => r.section === regressionLetter).map((r) => excelRow(story, r))),
});

const storyRows = stories.map((s) => ({
  section: s.section, ref: s.ref, jiraKey: s.jiraKey, jiraUrl: s.jiraUrl, qaKey: s.qaKey, qaUrl: s.qaUrl,
  title: s.title, origin: s.origin, acCount: s.acceptanceCriteria.length, generatedAc: s.generatedCriteria,
  tests: s.rows.length, coveragePct: s.quality.coveragePct,
  quality: s.testStatus === 'needs_clarification' ? 'Needs clarification' : s.quality.passed ? 'Passed' : 'Needs review',
  issues: [s.testStatus !== 'ok' ? s.statusReason : '', ...s.quality.issues, s.jiraError, s.qaError,
    ...s.assumptions.map((a) => `Assumption: ${a}`)].filter(Boolean),
}));

const traceability = stories.flatMap((s) => s.acceptanceCriteria.map((ac) => ({
  story: s.jiraKey || s.ref, acId: ac.id, acText: ac.text, source: ac.source,
  tests: s.rows.filter((r) => r.covers.includes(ac.id)).map((r) => r.id),
})));

const keyForRef = Object.fromEntries(stories.map((s) => [s.ref, s.jiraKey || s.ref]));
const questions = [
  ...(analysed?.analysis.openQuestions ?? []).map((q) => ({ story: keyForRef[q.storyRef] ?? q.storyRef ?? '', question: q.question })),
  ...stories.flatMap((s) => s.clarifyingQuestions.map((q) => ({ story: s.jiraKey || s.ref, question: q }))),
];

const sources = [
  ...files.files.map((f) => f.name),
  ...run.figmaUrls.map(() => 'Figma frame'),
  ...stories.filter((s) => s.action === 'fetch').map((s) => s.jiraKey),
];
const title = doc?.title || (stories.length === 1 ? stories[0].title : `Jira stories ${stories.map((s) => s.jiraKey).join(', ')}`);

// ── Usage and summary ────────────────────────────────────────────────────────
const usages = [analysed?.analysisUsage, ...stories.map((s) => s.usage)].filter(Boolean);
const inputTokens = usages.reduce((sum, u) => sum + (u.input_tokens ?? 0) + (u.cache_read_input_tokens ?? 0) + (u.cache_creation_input_tokens ?? 0), 0);
const outputTokens = usages.reduce((sum, u) => sum + (u.output_tokens ?? 0), 0);
const costUsd = Math.round(((inputTokens * PRICE_PER_MTOK.input + outputTokens * PRICE_PER_MTOK.output) / 1e6) * 100) / 100;

const count = (list, value) => list.filter((x) => x === value).length;
const origins = stories.map((s) => s.action);
const qa = stories.map((s) => s.qaOutcome ?? s.qaAction);
const totalTests = stories.reduce((n, s) => n + s.rows.length, 0);
const passed = stories.filter((s) => s.quality.passed).length;
const problems = [...stories.flatMap((s) => [s.jiraError, s.qaError]).filter(Boolean), ...skipped.map((s) => s.reason), ...files.warnings];

const lines = [
  `${totalTests} test cases in ${sections.filter((s) => s.rows.length).length} sections, for ${stories.length} stories.`,
  run.createInJira
    ? `Jira stories: ${count(origins, 'create')} created, ${count(origins, 'reuse') + count(origins, 'fetch')} already in Jira (not recreated). `
      + `QA tickets: ${count(qa, 'created')} created and linked, ${count(qa, 'updated')} updated.`
    : 'Preview mode: nothing was created in Jira.',
  `Quality gate: ${passed} of ${stories.length} stories passed. Claude usage about $${costUsd.toFixed(2)}.`,
  ...problems.map((p) => `Warning: ${p}`),
  'Your Excel test script is downloading.',
];

return [{
  json: {
    channel: run.channel,
    message: lines.join('\n'),
    summary: {
      stories: storyRows.map(({ issues, ...rest }) => rest),
      totalTests, sections: sections.length, qualityPassed: passed, inputTokens, outputTokens, costUsd, problems,
    },
    excel: {
      meta: {
        systemName: run.systemName || doc?.systemName || 'System',
        title,
        changeRequest: doc?.changeRequest || title,
        requestedDate: doc?.requestedDate || '',
        generatedAt: new Date().toLocaleString('en-GB', { dateStyle: 'long', timeStyle: 'short' }),
        model: run.settings.model,
        usage: `${inputTokens.toLocaleString('en-US')} input / ${outputTokens.toLocaleString('en-US')} output tokens (about $${costUsd.toFixed(2)})`,
        sources,
      },
      sections,
      stories: storyRows,
      traceability,
      questions,
    },
  },
}];
