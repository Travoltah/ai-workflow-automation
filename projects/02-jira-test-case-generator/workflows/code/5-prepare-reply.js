// NODE: "Prepare reply"  (Code node, mode: Run Once for All Items)
// Collects the results of this run into one item for whoever started it:
// the form gets the HTML page, an API caller gets JSON, the scheduled scan gets a summary.

const results = $('Format results').all().map((item) => item.json);

return [{
  json: {
    channel: results[0]?.channel ?? 'schedule',
    html: results[0]?.html ?? '',
    response: results.length === 1 ? results[0].apiResponse : results.map((r) => r.apiResponse),
    storiesProcessed: results.length,
    issueKeys: results.map((r) => r.issueKey).filter(Boolean),
  },
}];
