// NODE: "Remember QA comment"  (Code node, mode: Run Once for Each Item)
// Runs after "Comment on QA ticket": the story already had a QA ticket, so the new test cases
// were added to it as a comment instead of creating a second ticket.

const story = $('Lay out test script').item.json;
const error = $json.error;
const message = typeof error === 'string' ? error : [error?.message, error?.description].filter(Boolean).join(': ');

return {
  json: {
    ...story,
    qaCommentBody: null,
    qaOutcome: error ? 'failed' : 'updated',
    qaError: error ? `Could not comment on ${story.qaKey}: ${message}`.slice(0, 500) : '',
  },
};
