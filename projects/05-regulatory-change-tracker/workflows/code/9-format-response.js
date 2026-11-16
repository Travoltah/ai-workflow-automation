// NODE: "Format response"  (Code node, mode: Run Once for All Items)
// The API response and a short chat message for the finished run (reg.finish_run()).
const settings = $('Settings').first().json;
const s = $input.first().json.summary;
const triage = ($('Check triage').isExecuted ? $('Check triage') : $('No changes')).first().json;
const deferred = $('Plan briefs').first().json.deferred;

const relevant = s.changes.filter((c) => c.relevant);
const failed = s.source_checks.filter((c) => c.status === 'error');
const lines = [
  `*Regulatory change run #${s.run_id}*: ${s.sources_checked} sources checked${failed.length ? `, ${failed.length} failed (${failed.map((f) => f.code).join(', ')})` : ''}.`,
  `${s.changes_detected} change(s) detected · ${relevant.length} relevant · ${s.changes_analysed} briefed · $${Number(s.cost_usd).toFixed(2)}`,
  ...relevant.slice(0, 8).map((c) => `• [${c.jurisdiction}] ${c.title} (${c.priority || 'pending'}${c.status === 'flagged' ? ', flagged' : ''})`),
  relevant.length ? `Review: ${settings.reviewUrl}` : null,
].filter(Boolean);

return [{ json: {
  run_id: s.run_id,
  sources_checked: s.sources_checked,
  sources_failed: s.sources_failed,
  source_checks: s.source_checks,
  changes_detected: s.changes_detected,
  changes_relevant: relevant.length,
  changes_analysed: s.changes_analysed,
  deferred_to_next_run: deferred,
  triage_problems: triage.problems,
  usage: s.usage,
  cost_usd: Number(s.cost_usd),
  changes: s.changes,
  review_url: settings.reviewUrl,
  report_url: settings.reportUrl,
  chat_text: lines.join('\n'),
} }];
