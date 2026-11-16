// NODE: "Check explanations"  (Code node, mode: Run Once for All Items)
// The model proposes; the code decides. Every explanation is checked before it is stored or posted:
// - exactly one explanation per new incident, for a rule that actually failed
// - evidence ids must be ids Claude was shown (no invented records)
// - related rules must be other rules that failed in this run
// - severity and confidence come from the allowed lists (the JSON schema enforces this too)
// An incident whose explanation fails the check gets a plain fallback, marked explanation_ok = false.
// Also returns token usage and cost for the run log.

const plan = $('Plan explanations').first().json;
const response = $input.first().json;
const model = $('Settings').first().json.model;

// USD per million tokens (input, output). Add your model here if you switch; unknown models are costed at Opus prices.
const PRICES = { 'claude-opus-5-5': [4, 20], 'claude-haiku-5-5': [0.1, 0.5] };

const newOnes = plan.result.actions.filter((a) => a.action === 'new');
const failedCodes = new Set(plan.result.actions.filter((a) => a.action !== 'resolved').map((a) => a.rule_code));
const problems = [];

let parsed = null;
if (response.error) {
  problems.push(`Claude call failed: ${JSON.stringify(response.error).slice(0, 300)}`);
} else if (response.stop_reason === 'refusal') {
  problems.push('Claude declined the request.');
} else if (response.stop_reason === 'max_tokens') {
  problems.push('The answer was cut off (max_tokens); raise MAX_TOKENS in "Plan explanations".');
} else {
  try {
    parsed = JSON.parse((response.content || []).find((b) => b.type === 'text')?.text || '');
  } catch (e) {
    problems.push(`Answer was not valid JSON: ${e.message}`);
  }
}

const byRule = new Map();
for (const e of parsed?.incidents || []) {
  if (!failedCodes.has(e.rule_code)) { problems.push(`Explanation for a rule that did not fail: ${e.rule_code}`); continue; }
  if (byRule.has(e.rule_code)) { problems.push(`Two explanations for ${e.rule_code}; kept the first`); continue; }
  byRule.set(e.rule_code, e);
}

const explanations = newOnes.map((a) => {
  const e = byRule.get(a.rule_code);
  const issues = [];
  if (!e) issues.push('no explanation returned');
  else {
    const shown = new Set(plan.sentSamples[a.rule_code] || []);
    const invented = e.evidence_ids.filter((id) => !shown.has(id));
    if (invented.length) issues.push(`evidence ids not in the sample: ${invented.join(', ')}`);
    const badRelated = e.related_rules.filter((r) => !failedCodes.has(r) || r === a.rule_code);
    if (badRelated.length) issues.push(`related rules that did not fail: ${badRelated.join(', ')}`);
    for (const f of ['likely_cause', 'business_impact', 'suggested_fix']) if (!String(e[f] || '').trim()) issues.push(`empty ${f}`);
  }
  if (issues.length) problems.push(`${a.rule_code}: ${issues.join('; ')}`);
  const ok = issues.length === 0;
  return {
    incident_id: a.incident_id,
    rule_code: a.rule_code,
    explanation_ok: ok,
    explanation: ok
      ? { ...e, model, check: 'passed' }
      : {
          rule_code: a.rule_code,
          likely_cause: 'Not explained: the AI explanation was missing or failed the automatic check. Investigate from the rule and the evidence below.',
          business_impact: a.description,
          suggested_fix: `Review the failing records with the check SQL, then contact the owner (${a.owner}).`,
          assessed_severity: a.severity, confidence: 'low', evidence_ids: [], related_rules: [],
          model, check: `failed: ${issues.join('; ')}`,
        },
  };
});

const u = response.usage || {};
const inputTokens = (u.input_tokens || 0) + (u.cache_read_input_tokens || 0) + (u.cache_creation_input_tokens || 0);
const outputTokens = u.output_tokens || 0;
const [pin, pout] = PRICES[model] || PRICES['claude-opus-5-5'];
const cost = Math.round(((inputTokens * pin + outputTokens * pout) / 1e6) * 10000) / 10000;

return [{
  json: {
    explanations,
    runSummaryText: parsed?.summary || '',
    problems,
    usage: { model, input_tokens: inputTokens, output_tokens: outputTokens, cost_usd: cost },
  },
}];
