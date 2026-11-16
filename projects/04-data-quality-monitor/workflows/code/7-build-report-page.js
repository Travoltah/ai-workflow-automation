// NODE: "Build report page"  (Code node, mode: Run Once for All Items)
// Turns dq.report() into a self-contained HTML page: latest run, every rule's status,
// the explained failures, and the pass rate over recent runs. Served at GET /webhook/dq/report.
const rep = $input.first().json.report;
const latest = rep.latest;
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const sevTone = { critical: 'bad', high: 'warn', medium: 'note', low: '' };
const badge = (text, tone = '') => `<span class="badge ${tone}">${esc(text)}</span>`;

let body;
if (!latest) {
  body = '<h1>Data quality monitor</h1><p class="muted">No finished runs yet. Trigger one with POST /webhook/dq/run or wait for the schedule.</p>';
} else {
  const passed = latest.checks_run - latest.checks_failed - latest.checks_errored;
  const when = new Date(latest.finished_at || latest.started_at).toUTCString().replace(' GMT', ' UTC');
  const byTable = {};
  for (const r of rep.rules) (byTable[r.table_name] ||= []).push(r);
  const maxRuns = Math.max(...rep.history.map((h) => h.checks_run), 1);

  body = `
<h1>Data quality monitor · Contoso Pay</h1>
<div class="muted">Run #${latest.run_id} · ${esc(when)} · triggered by ${esc(latest.trigger)}</div>
<div class="kpis">
  <div class="kpi ${latest.checks_failed ? 'bad' : 'good'}"><b>${latest.pass_rate_pct ?? 0}%</b><span>checks passed (${passed} of ${latest.checks_run})</span></div>
  <div class="kpi"><b>${latest.checks_failed}</b><span>failed checks</span></div>
  <div class="kpi"><b>${rep.open_incidents}</b><span>open incidents now</span></div>
  <div class="kpi"><b>$${Number(latest.cost_usd || 0).toFixed(2)}</b><span>AI cost this run</span></div>
</div>

<h2>Checks by table</h2>
<div class="grid">${Object.entries(byTable).map(([table, rules]) => `
  <div class="card"><div class="label">${esc(table)}</div>
  ${rules.map((r) => `<div class="rule"><span class="dot ${r.status === 'pass' ? 'good' : r.status === 'fail' ? 'bad' : 'warn'}"></span>
    <span>${esc(r.rule_name)}</span><span class="muted">${r.status === 'fail' ? `${r.failing_count} rec.` : esc(r.status || 'n/a')}</span></div>`).join('')}
  </div>`).join('')}
</div>

${latest.failures.length ? `<h2>Failures, with explanations</h2>${latest.failures.map((f) => {
    const e = f.explanation || {};
    return `<div class="card fail">
  <div class="head"><h3>${esc(f.rule_name)}</h3>${badge(f.severity, sevTone[f.severity])}${badge(`${f.failing_count} record(s)`)}${badge(f.dimension)}${f.jira_key ? badge(f.jira_key, 'note') : ''}${f.opened_run !== latest.run_id ? badge(`open since run #${f.opened_run}`) : badge('new', 'bad')}</div>
  <div class="muted">${esc(f.table_name)} · ${esc(f.rule_code)}</div>
  ${f.explanation ? `
  <p><span class="label">Likely cause</span> ${esc(e.likely_cause)} <span class="muted">(confidence: ${esc(e.confidence)})</span></p>
  <p><span class="label">Impact</span> ${esc(e.business_impact)}</p>
  <p><span class="label">Fix</span> ${esc(e.suggested_fix)}</p>
  ${f.explanation_ok === false ? `<p class="warnline">The AI explanation failed the automatic check and was not used: ${esc(e.check)}</p>` : ''}` : '<p class="muted">No explanation stored.</p>'}
  <details><summary>Evidence (first ${f.sample_rows.length})</summary><table><tr><th>Record</th><th>Detail</th></tr>
  ${f.sample_rows.map((r) => `<tr><td>${esc(r.record_id)}</td><td>${esc(r.detail)}</td></tr>`).join('')}</table></details>
</div>`;
  }).join('')}` : '<div class="card good-card">Every check passed. No open data quality issues.</div>'}

${latest.resolved.length ? `<h2>Resolved in this run</h2><div class="card">${latest.resolved.map((r) => badge(`${r.rule_code}${r.jira_key ? ` · ${r.jira_key}` : ''}`, 'good')).join(' ')}</div>` : ''}

<h2>Recent runs</h2>
<div class="card"><div class="bars">${rep.history.map((h) => {
    const pass = h.checks_run - h.checks_failed - h.checks_errored;
    return `<div class="bar" title="Run #${h.run_id}: ${pass}/${h.checks_run} passed">
      <div class="fill good" style="height:${(pass / maxRuns) * 100}%"></div><div class="fill bad" style="height:${(h.checks_failed / maxRuns) * 100}%"></div>
      <span>#${h.run_id}</span></div>`;
  }).join('')}</div><div class="muted">Green = checks passed, red = checks failed, per run.</div></div>
<p class="muted">Check results are deterministic SQL. Causes, impacts and fixes are written by AI, checked by code, and should be reviewed before acting.</p>`;
}

const html = `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Data quality monitor</title>
<style>
  body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#f4f6fb;color:#1f2937}
  main{max-width:1040px;margin:0 auto;padding:24px 16px 48px}
  h1{font-size:22px;margin:0 0 4px} h2{font-size:16px;margin:28px 0 10px} h3{font-size:15px;margin:0}
  .muted{color:#6b7280;font-size:13px} .label{font-weight:600;font-size:12px;color:#374151;text-transform:uppercase;letter-spacing:.03em;margin-right:6px}
  .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin:16px 0}
  .kpi{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px} .kpi b{display:block;font-size:26px} .kpi span{color:#6b7280;font-size:13px}
  .kpi.good b{color:#15803d} .kpi.bad b{color:#b91c1c}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:10px}
  .card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px;margin:10px 0} .grid .card{margin:0}
  .card.fail{border-left:4px solid #dc2626} .good-card{border-left:4px solid #16a34a}
  .rule{display:grid;grid-template-columns:14px 1fr auto;gap:8px;align-items:center;font-size:13px;padding:4px 0}
  .dot{width:10px;height:10px;border-radius:50%} .dot.good{background:#16a34a} .dot.bad{background:#dc2626} .dot.warn{background:#d97706}
  .head{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
  .badge{font-size:12px;padding:2px 9px;border-radius:999px;background:#eef2ff;color:#3730a3}
  .badge.bad{background:#fee2e2;color:#991b1b} .badge.warn{background:#ffedd5;color:#9a3412} .badge.note{background:#fef9c3;color:#854d0e} .badge.good{background:#dcfce7;color:#166534}
  p{margin:8px 0;font-size:14px;line-height:1.45} .warnline{color:#9a3412;font-size:13px}
  table{width:100%;border-collapse:collapse;font-size:12px;margin-top:6px} th,td{text-align:left;padding:5px 6px;border-bottom:1px solid #e5e7eb} th{background:#f9fafb}
  details summary{cursor:pointer;font-size:13px;color:#374151;margin-top:4px}
  .bars{display:flex;gap:6px;align-items:flex-end;height:120px;padding-top:6px}
  .bar{flex:1;max-width:38px;height:100%;display:flex;flex-direction:column-reverse;position:relative}
  .bar span{position:absolute;bottom:-18px;width:100%;text-align:center;font-size:10px;color:#6b7280}
  .fill.good{background:#16a34a} .fill.bad{background:#dc2626}
  .bars+.muted{margin-top:24px}
</style></head><body><main>${body}</main></body></html>`;

return [{ json: { html } }];
