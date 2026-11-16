// NODE: "Format result"  (Code node, mode: Run Once for All Items)
// The API response: the application status, what the customer must do, every check, and the AI cost.
const v = $input.first().json;                      // from the intake service's /validate
const start = ($('Intake results').isExecuted ? $('Intake results') : $('Read process request')).first().json;
const read = ($('Check extractions').isExecuted ? $('Check extractions') : $('Nothing to read')).first().json;
return [{ json: {
  application_id: v.application_id,
  reference: $('Read submission').isExecuted ? $('Read submission').first().json.reference : null,
  status: v.status,
  customer_actions: v.customer_actions,
  summary: v.summary,
  documents: v.documents,
  intake: start.intake,
  checks: v.checks,
  ai_calls: read.calls,
  ai_problems: read.problems,
  cost_usd: read.cost_usd,
  review_url: $('Settings').first().json.reviewUrl,
} }];
