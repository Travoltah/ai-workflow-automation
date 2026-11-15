// NODE: "Remember story key"  (Code node, mode: Run Once for Each Item)
// Runs after "Create Jira story": adds the new key to the story, or records why Jira refused it.

const story = $('Plan stories').item.json;
const run = $('Collect inputs').item.json;
const error = $json.error;
const message = typeof error === 'string' ? error : [error?.message, error?.description].filter(Boolean).join(': ');

return {
  json: {
    ...story,
    jiraCreateBody: null,
    jiraKey: error ? '' : $json.key,
    jiraUrl: error ? '' : `${run.settings.jiraBaseUrl}/browse/${$json.key}`,
    origin: error ? 'Not created in Jira (error)' : story.origin,
    jiraError: error ? `Jira did not create the story: ${message}`.slice(0, 500) : '',
  },
};
