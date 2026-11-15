// NODE: "Remember QA ticket"  (Code node, mode: Run Once for Each Item)
// Runs after "Create QA ticket" and "Link QA ticket to story": keeps the new key, or why it failed.

const story = $('Lay out test script').item.json;
const created = $('Create QA ticket').item.json;
const settings = $('Collect inputs').item.json.settings;
const describe = (error) => (typeof error === 'string' ? error : [error?.message, error?.description].filter(Boolean).join(': '));

const errors = [];
if (created.error) errors.push(`Jira did not create the QA ticket: ${describe(created.error)}`);
else if ($json.error) errors.push(`QA ticket ${created.key} was created but not linked to ${story.jiraKey}: ${describe($json.error)}`);

return {
  json: {
    ...story,
    qaCreateBody: null,
    qaKey: created.key ?? '',
    qaUrl: created.key ? `${settings.jiraBaseUrl}/browse/${created.key}` : '',
    qaOutcome: created.key ? 'created' : 'failed',
    qaError: errors.join(' ').slice(0, 500),
  },
};
