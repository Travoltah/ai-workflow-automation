// NODE: "Plan Jira tasks"  (Code node, mode: Run Once for All Items)
// One Jira task per control the approved change affects, assigned by owner in the summary,
// due on the earliest effective / compliance / comment date in the brief.
const settings = $('Settings').first().json;
const r = $input.first().json.result;              // reg.decide()
if (!settings.jiraEnabled || !r.ok || r.decision !== 'approve') return [];
const b = r.change.brief || {};
const base = settings.jiraBaseUrl.replace(/\/$/, '');
const cell = (v) => String(v ?? '').replace(/[{}|]/g, '').replace(/\r?\n/g, ' ');

return r.tasks.map((t) => ({ json: {
  task_id: t.task_id,
  url: `${base}/rest/api/2/issue`,
  body: { fields: {
    project: { key: settings.jiraProjectKey },
    issuetype: { name: settings.jiraIssueType },
    summary: `[Reg][${r.change.jurisdiction}] Review ${t.control_name}: ${r.change.title}`.slice(0, 250),
    ...(t.due_date ? { duedate: t.due_date } : {}),
    labels: ['regulatory-change', `jurisdiction-${r.change.jurisdiction.toLowerCase()}`, `control-${t.control_id.toLowerCase()}`],
    description: [
      `h3. ${cell(r.change.title)}`,
      `${cell(r.change.regulator)} · [source|${r.change.url}] · priority *${r.change.priority}*`,
      '', `*Control:* ${t.control_id} (${cell(t.control_name)}) · *Owner:* ${cell(t.owner)}${t.due_date ? ` · *Due:* ${t.due_date}` : ''}`,
      `*Why:* ${cell(t.why)}`,
      '', 'h4. Summary', cell(b.summary),
      ...(b.obligations?.length ? ['', 'h4. Obligations (quoted from the source)', ...b.obligations.map((o) => `* ${cell(o.text)} — _"${cell(o.quote)}"_`)] : []),
      ...(b.key_dates?.length ? ['', 'h4. Dates', ...b.key_dates.map((k) => `* ${k.date} (${k.type}) — _"${cell(k.quote)}"_`)] : []),
      '', `_Approved by ${cell($('Read decision').first().json.reviewer)} after review. Brief written by AI, quotes and dates checked by code. Not legal advice._`,
    ].join('\n'),
  } },
} }));
