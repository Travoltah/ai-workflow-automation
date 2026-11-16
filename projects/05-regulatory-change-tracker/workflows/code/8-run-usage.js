// NODE: "Run usage"  (Code node, mode: Run Once for All Items)
// Adds up tokens and cost across both models (triage + briefs) for the run log.
// USD per million tokens (input, output). Unknown models are costed at Opus prices.
const PRICES = { 'claude-opus-5-5': [4, 20], 'claude-haiku-5-5': [0.1, 0.5] };
const settings = $('Settings').first().json;

const calls = [];
if ($('Check triage').isExecuted) calls.push({ model: settings.triageModel, usage: $('Check triage').first().json.usage });
if ($('Verify briefs').isExecuted) for (const b of $('Verify briefs').first().json.briefs) calls.push({ model: b.brief.model, usage: b.usage });

const byModel = {};
let cost = 0;
for (const { model, usage } of calls) {
  if (!usage) continue;
  const input = (usage.input_tokens || 0) + (usage.cache_read_input_tokens || 0) + (usage.cache_creation_input_tokens || 0);
  const output = usage.output_tokens || 0;
  const m = (byModel[model] ||= { calls: 0, input_tokens: 0, output_tokens: 0 });
  m.calls += 1; m.input_tokens += input; m.output_tokens += output;
  const [pin, pout] = PRICES[model] || PRICES['claude-opus-5-5'];
  cost += (input * pin + output * pout) / 1e6;
}
return [{ json: { runId: $('Plan triage').first().json.runId, usage: byModel, cost: Math.round(cost * 10000) / 10000 } }];
