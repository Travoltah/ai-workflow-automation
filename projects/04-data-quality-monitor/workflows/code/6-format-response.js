// NODE: "Format response"  (Code node, mode: Run Once for All Items)
// Builds the API response and the chat message from the finished run (dq.finish_run()).
const settings = $('Settings').first().json;
const summary = $input.first().json.summary;          // jsonb from dq.finish_run()
const checked = ($('Check explanations').isExecuted ? $('Check explanations') : $('No new failures')).first().json;
const actions = $('Plan explanations').first().json.result.actions;
const count = (kind) => actions.filter((a) => a.action === kind).length;
const jira = $('Collect Jira keys').isExecuted ? $('Collect Jira keys').first().json : { keys: [], failures: [] };

const icon = { critical: '🔴', high: '🟠', medium: '🟡', low: '⚪' };
const lines = [
  `*Data quality run #${summary.run_id}*: ${summary.checks_run - summary.checks_failed - summary.checks_errored} of ${summary.checks_run} checks passed (${summary.pass_rate_pct}%).`,
  `${count('new')} new · ${count('ongoing')} ongoing · ${count('resolved')} resolved${summary.checks_errored ? ` · ${summary.checks_errored} check(s) errored` : ''}`,
  checked.runSummaryText ? `> ${checked.runSummaryText}` : null,
  ...summary.failures.slice(0, 10).map((f) => `${icon[f.severity] || '•'} ${f.rule_name}: ${f.failing_count} record(s)${f.jira_key ? ` (${f.jira_key})` : ''}`),
  `Report: ${settings.reportUrl}`,
].filter(Boolean);

return [{
  json: {
    run_id: summary.run_id,
    checks_run: summary.checks_run,
    checks_failed: summary.checks_failed,
    checks_errored: summary.checks_errored,
    pass_rate_pct: summary.pass_rate_pct,
    new_incidents: count('new'),
    ongoing_incidents: count('ongoing'),
    resolved_incidents: count('resolved'),
    ai_summary: checked.runSummaryText,
    explanation_problems: checked.problems,
    jira_failures: jira.failures,
    usage: { model: summary.model, input_tokens: summary.input_tokens, output_tokens: summary.output_tokens, cost_usd: summary.cost_usd },
    failures: summary.failures.map((f) => ({
      rule_code: f.rule_code, rule_name: f.rule_name, severity: f.severity, failing_count: f.failing_count,
      record_ids: f.record_ids, jira_key: f.jira_key, explanation_ok: f.explanation_ok, explanation: f.explanation,
    })),
    resolved: summary.resolved,
    errors: summary.errors,
    report_url: settings.reportUrl,
    chat_text: lines.join('\n'),
  },
}];
