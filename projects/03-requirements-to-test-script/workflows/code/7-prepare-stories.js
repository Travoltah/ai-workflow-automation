// NODE: "Prepare stories"  (Code node, mode: Run Once for All Items)
// Joins the three routes (created, read from Jira, kept as they were) back into the
// original order, and sets aside stories that could not be read so the run can go on.

const all = $input.all().map((item) => item.json).sort((a, b) => a.seq - b.seq);
const skipped = all.filter((s) => s.origin === 'Could not read from Jira')
  .map((s) => ({ ref: s.ref, jiraKey: s.jiraKey, reason: s.jiraError }));
const stories = all.filter((s) => s.origin !== 'Could not read from Jira');
if (!stories.length) throw new Error(`None of the stories could be read: ${skipped.map((s) => s.reason).join(' | ')}`);

return stories.map((story) => ({ json: { ...story, skipped } }));
