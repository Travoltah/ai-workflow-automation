// NODE: "No new failures"  (Code node, mode: Run Once for All Items)
// The branch for runs with no new incidents: nothing to explain, no Claude call, no cost.
// Returns the same shape as "Check explanations" so the rest of the workflow is identical.
return [{
  json: {
    explanations: [],
    runSummaryText: '',
    problems: [],
    usage: { model: null, input_tokens: 0, output_tokens: 0, cost_usd: 0 },
  },
}];
