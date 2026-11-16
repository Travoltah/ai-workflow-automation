// NODE: "Plan Jira updates"  (Code node, mode: Run Once for All Items)
// One Jira request per incident change:
//   new      -> create a Bug with the checked explanation, the evidence and the SQL to reproduce it
//   ongoing  -> comment on the existing ticket with the new count (no AI call, no new ticket)
//   resolved -> comment that the check passes again
// Returns no items when Jira is switched off in Settings, or when nothing changed.

const settings = $('Settings').first().json;
if (!settings.jiraEnabled) return [];

const plan = $('Plan explanations').first().json;
const checked = ($('Check explanations').isExecuted ? $('Check explanations') : $('No new failures')).first().json;
const explained = new Map(checked.explanations.map((e) => [e.incident_id, e]));
const run = plan.result.run_id;
const base = settings.jiraBaseUrl.replace(/\/$/, '');

// Jira wiki markup: keep table cells and text from breaking the layout.
const cell = (v) => String(v ?? '').replace(/\|/g, '/').replace(/[{}]/g, '').replace(/\r?\n/g, ' ');

const items = [];
for (const a of plan.result.actions) {
  if (a.action === 'new') {
    const e = explained.get(a.incident_id)?.explanation || {};
    const ok = explained.get(a.incident_id)?.explanation_ok;
    const description = [
      'h3. What failed',
      `*${a.rule_name}*: *${a.failing_count}* record(s) in {{${a.table_name}}}.`,
      `Dimension: ${a.dimension} · Rule severity: *${a.severity}* · Owner: ${a.owner} · Rule: {{${a.rule_code}}} · Run #${run}`,
      a.description,
      '',
      `h3. Likely cause${ok ? ' (AI, checked)' : ''}`,
      cell(e.likely_cause),
      `_Confidence: ${e.confidence || 'n/a'} · AI-assessed severity: ${e.assessed_severity || 'n/a'}_`,
      e.related_rules?.length ? `_Probably related to: ${e.related_rules.join(', ')}_` : '',
      '',
      'h3. Business impact',
      cell(e.business_impact),
      '',
      'h3. Suggested fix',
      cell(e.suggested_fix),
      '',
      `h3. Evidence (first ${(a.sample_rows || []).length} of ${a.failing_count})`,
      '||Record||Detail||',
      ...(a.sample_rows || []).map((r) => `|${cell(r.record_id)}|${cell(r.detail)}|`),
      '',
      'h3. Reproduce',
      `{code:sql}\n${a.check_sql}\n{code}`,
      '',
      `_The check result is deterministic SQL. The cause, impact and fix are written by ${e.model || 'the AI'} and checked by code before posting. Review before acting._`,
    ].filter((line) => line !== null).join('\n');

    items.push({ json: {
      incident_id: a.incident_id, kind: 'create', rule_code: a.rule_code,
      url: `${base}/rest/api/2/issue`,
      body: { fields: {
        project: { key: settings.jiraProjectKey },
        issuetype: { name: settings.jiraIssueType },
        summary: `[DQ][${a.severity}] ${a.rule_name}: ${a.failing_count} record(s) in ${a.table_name}`,
        description,
        labels: ['data-quality', `dq-${a.rule_code.toLowerCase().replace(/_/g, '-')}`],
      } },
    } });
  } else if (a.jira_key) {
    const text = a.action === 'ongoing'
      ? `Still failing in data quality run #${run}: *${a.failing_count}* record(s) (previous run: ${a.previous_count}).`
      : `Resolved in data quality run #${run}: the check passes again (last failing count: ${a.previous_count}). Close this ticket once the fix is confirmed.`;
    items.push({ json: { incident_id: a.incident_id, kind: 'comment', rule_code: a.rule_code,
      url: `${base}/rest/api/2/issue/${a.jira_key}/comment`, body: { body: text } } });
  }
}
return items;
