// NODE: "Decision response"  (Code node, mode: Run Once for All Items)
// JSON for API clients; a small HTML page (with a link back to the queue) for the review form.
const settings = $('Settings').first().json;
const input = $('Read decision').first().json;
const r = $('Record decision').first().json.result;
const jira = $('Collect task keys').isExecuted ? $('Collect task keys').first().json : { keys: [], failures: [] };
const keyOf = new Map(jira.keys.map((k) => [k.task_id, k.jira_key]));
const tasks = (r.tasks || []).map((t) => ({ ...t, jira_key: keyOf.get(t.task_id) || null }));
const result = { ok: r.ok, error: r.error || null, change_id: r.change_id ?? input.change_id, decision: r.decision ?? input.decision, tasks, jira_failures: jira.failures };

const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const html = `<!doctype html><html><head><meta charset="utf-8"><title>Decision recorded</title>
<style>body{font-family:system-ui,Segoe UI,sans-serif;background:#f4f6fb;color:#1f2937} main{max-width:640px;margin:40px auto;background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:24px}</style></head>
<body><main>${r.ok
  ? `<h2>${result.decision === 'approve' ? 'Approved' : 'Dismissed'}: change #${result.change_id}</h2>${tasks.length ? `<p>${tasks.length} task(s) created:</p><ul>${tasks.map((t) => `<li>${esc(t.jira_key || 'no Jira key')}: ${esc(t.control_name)} (${esc(t.owner)}${t.due_date ? `, due ${esc(t.due_date)}` : ''})</li>`).join('')}</ul>` : '<p>No tasks created.</p>'}`
  : `<h2>Not recorded</h2><p>${esc(result.error)}</p>`}
<p><a href="${esc(settings.reviewUrl)}">Back to the review queue</a></p></main></body></html>`;

return [{ json: { ...result, html, fromForm: input.fromForm } }];
