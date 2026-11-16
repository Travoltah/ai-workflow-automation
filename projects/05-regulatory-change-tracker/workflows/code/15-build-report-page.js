// NODE: "Build report page"  (Code node, mode: Run Once for All Items)
// Overview: source health, the latest run, changes by jurisdiction, and upcoming deadlines.
const rep = $input.first().json.report;
const settings = $('Settings').first().json;
const L = rep.latest;
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const badge = (t, tone = '') => `<span class="badge ${tone}">${esc(t)}</span>`;
const statusTone = { ok: 'good', baseline: '', empty: 'warn', error: 'bad', approved: 'good', dismissed: '', flagged: 'warn', analysed: 'note', not_relevant: '', relevant: 'note' };
const days = (d) => Math.round((new Date(`${d}T00:00:00Z`) - new Date(new Date().toISOString().slice(0, 10))) / 86400000);
const active = rep.sources.filter((s) => s.active);
const failing = active.filter((s) => s.last_status === 'error');

const body = `
<h1>Regulatory change tracker · AI &amp; data governance</h1>
<div class="muted">${L ? `Run #${L.run_id} · ${esc(new Date(L.finished_at).toUTCString().replace(' GMT', ' UTC'))} · triggered by ${esc(L.trigger)}` : 'No finished runs yet'}</div>
<div class="kpis">
  <div class="kpi"><b>${active.length}</b><span>sources monitored (${new Set(active.map((s) => s.jurisdiction)).size} markets)</span></div>
  <div class="kpi ${failing.length ? 'bad' : 'good'}"><b>${failing.length}</b><span>sources failing</span></div>
  <div class="kpi"><b>${L ? L.changes_detected : 0}</b><span>changes in the latest run (${L ? L.changes_relevant : 0} relevant)</span></div>
  <div class="kpi"><b>${rep.pending_review}</b><span><a href="${esc(settings.reviewUrl)}">waiting for review</a></span></div>
  <div class="kpi"><b>$${L ? Number(L.cost_usd).toFixed(2) : '0.00'}</b><span>AI cost, latest run</span></div>
</div>

<h2>Upcoming deadlines</h2>
<div class="card">${rep.deadlines.length ? `<table><tr><th>Date</th><th>In</th><th>Type</th><th>Market</th><th>Publication</th><th>Status</th></tr>
${rep.deadlines.map((d) => `<tr><td><b>${esc(d.date)}</b></td><td>${days(d.date)} days</td><td>${esc(d.type.replace('_', ' '))}</td><td>${esc(d.jurisdiction)}</td><td>${esc(d.title)}</td><td>${badge(d.status, statusTone[d.status])}</td></tr>`).join('')}</table>` : '<span class="muted">No upcoming dates.</span>'}</div>

${L ? `<h2>Run #${L.run_id}: what changed</h2>
<div class="card"><table><tr><th>Market</th><th>Publication</th><th>Change</th><th>Triage</th><th>Status</th><th>Priority</th></tr>
${L.changes.map((c) => `<tr><td>${esc(c.jurisdiction)}</td><td><a href="${esc(c.url)}">${esc(c.title)}</a>${c.brief ? `<div class="muted">${esc(c.brief.summary)}</div>` : ''}</td><td>${esc(c.change_type)}</td>
<td>${c.relevant ? badge('relevant', 'note') : badge('not relevant')}<div class="muted">${esc(c.triage_reason)}</div></td><td>${badge(c.status, statusTone[c.status])}</td><td>${esc(c.priority || '')}</td></tr>`).join('') || '<tr><td colspan="6" class="muted">Nothing changed.</td></tr>'}</table></div>` : ''}

<h2>Changes by market (90 days)</h2>
<div class="card"><table><tr><th>Market</th><th>Changes</th><th>Relevant</th><th>Waiting for review</th><th>Approved</th></tr>
${rep.by_jurisdiction.map((j) => `<tr><td><b>${esc(j.jurisdiction)}</b></td><td>${j.changes}</td><td>${j.relevant}</td><td>${j.pending_review}</td><td>${j.approved}</td></tr>`).join('') || '<tr><td colspan="5" class="muted">No changes yet.</td></tr>'}</table></div>

<h2>Sources</h2>
<div class="card"><table><tr><th>Market</th><th>Publisher</th><th>Source</th><th>Method</th><th>Last check</th></tr>
${rep.sources.map((s) => `<tr class="${s.active ? '' : 'off'}"><td>${esc(s.jurisdiction)}</td><td>${esc(s.regulator)}</td><td>${esc(s.name)}${s.is_mock ? ' <span class="muted">(mock)</span>' : ''}</td><td>${esc(s.method)}</td>
<td>${s.active ? badge(s.last_status || 'never', statusTone[s.last_status]) : badge('off')}${s.last_error ? `<div class="muted">${esc(s.last_error.slice(0, 140))}</div>` : ''}</td></tr>`).join('')}</table></div>
<p class="muted">Briefs are written by AI and checked by code (quotes word for word, dates, controls), then reviewed by a person. Not legal advice.</p>`;

const html = `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Regulatory change tracker</title>
<style>
  body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#f4f6fb;color:#1f2937}
  main{max-width:1100px;margin:0 auto;padding:24px 16px 48px} h1{font-size:22px;margin:0 0 4px} h2{font-size:16px;margin:28px 0 10px}
  .muted{color:#6b7280;font-size:12px} .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin:16px 0}
  .kpi{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px} .kpi b{display:block;font-size:26px} .kpi span{color:#6b7280;font-size:13px}
  .kpi.good b{color:#15803d} .kpi.bad b{color:#b91c1c} .card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:12px 14px}
  table{width:100%;border-collapse:collapse;font-size:13px} th,td{text-align:left;padding:7px 8px;border-bottom:1px solid #e5e7eb;vertical-align:top} th{background:#f9fafb}
  tr.off td{color:#9ca3af} .badge{font-size:12px;padding:2px 9px;border-radius:999px;background:#eef2ff;color:#3730a3;white-space:nowrap}
  .badge.bad{background:#fee2e2;color:#991b1b} .badge.warn{background:#ffedd5;color:#9a3412} .badge.note{background:#fef9c3;color:#854d0e} .badge.good{background:#dcfce7;color:#166534}
  a{color:#1d4ed8}
</style></head><body><main>${body}</main></body></html>`;
return [{ json: { html } }];
