// NODE: "Build review page"  (Code node, mode: Run Once for All Items)
// The human step: every brief waiting for a decision, with its verified quotes, dates, controls and
// any problems the check found. Approve creates one task per affected control; Dismiss creates none.
const queue = $input.first().json.queue || [];
const decideUrl = $('Settings').first().json.decideUrl;
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const badge = (t, tone = '') => `<span class="badge ${tone}">${esc(t)}</span>`;
const tone = { high: 'bad', medium: 'warn', low: '' };

const cards = queue.map((c) => {
  const b = c.brief || {};
  const v = c.verification || {};
  return `<div class="card ${c.status === 'flagged' ? 'flag' : ''}">
  <div class="head"><h3>${esc(c.title)}</h3>${badge(c.jurisdiction)}${badge(c.priority + ' priority', tone[c.priority])}${badge(c.applicability.replace('_', ' '))}${badge(c.change_type)}${c.status === 'flagged' ? badge('flagged by the check', 'bad') : badge('check passed', 'good')}</div>
  <div class="muted">${esc(c.regulator)} · <a href="${esc(c.url)}">source</a> · ${esc(b.instrument_type)} · ${esc(b.status)} · ${esc(b.binding)} · confidence ${esc(b.confidence)}</div>
  <p>${esc(b.summary)}</p>
  ${b.what_changed ? `<p><span class="label">What changed</span>${esc(b.what_changed)}</p>` : ''}
  ${b.key_dates?.length ? `<p><span class="label">Dates</span></p><ul>${b.key_dates.map((k) => `<li><b>${esc(k.date)}</b> ${esc(k.type.replace('_', ' '))}: <q>${esc(k.quote)}</q></li>`).join('')}</ul>` : ''}
  ${b.obligations?.length ? `<p><span class="label">Obligations</span></p><ul>${b.obligations.map((o) => `<li>${esc(o.text)} <span class="muted">(${esc(o.applies_to)})</span><br><q>${esc(o.quote)}</q></li>`).join('')}</ul>` : ''}
  ${b.affected_controls?.length ? `<p><span class="label">Controls to review</span></p><ul>${b.affected_controls.map((a) => `<li><b>${esc(a.control_id)}</b>: ${esc(a.why)}</li>`).join('')}</ul>` : ''}
  ${v.removed?.length ? `<p class="warnline">The automatic check removed: ${esc(v.removed.join(' · '))}</p>` : ''}
  <form method="post" action="${esc(decideUrl)}">
    <input type="hidden" name="change_id" value="${c.change_id}">
    <input name="reviewer" placeholder="Your name" required> <input name="note" placeholder="Note (optional)" size="40">
    <button name="decision" value="approve" class="approve">Approve: create ${b.affected_controls?.length || 0} task(s)</button>
    <button name="decision" value="dismiss" class="dismiss">Dismiss</button>
  </form>
</div>`;
}).join('');

const html = `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Regulatory changes: review</title>
<style>
  body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#f4f6fb;color:#1f2937}
  main{max-width:980px;margin:0 auto;padding:24px 16px 48px} h1{font-size:22px;margin:0 0 4px} h3{font-size:16px;margin:0}
  .muted{color:#6b7280;font-size:13px} .label{font-weight:600;font-size:12px;color:#374151;text-transform:uppercase;letter-spacing:.03em;margin-right:6px}
  .card{background:#fff;border:1px solid #e5e7eb;border-left:4px solid #2563eb;border-radius:10px;padding:16px;margin:14px 0} .card.flag{border-left-color:#d97706}
  .head{display:flex;flex-wrap:wrap;gap:6px;align-items:center} p,li{font-size:14px;line-height:1.45} q{color:#374151;font-style:italic}
  .badge{font-size:12px;padding:2px 9px;border-radius:999px;background:#eef2ff;color:#3730a3}
  .badge.bad{background:#fee2e2;color:#991b1b} .badge.warn{background:#ffedd5;color:#9a3412} .badge.good{background:#dcfce7;color:#166534}
  .warnline{color:#9a3412;font-size:13px} form{margin-top:12px;display:flex;flex-wrap:wrap;gap:8px} input{padding:6px 8px;border:1px solid #d1d5db;border-radius:6px}
  button{padding:7px 12px;border-radius:6px;border:0;cursor:pointer;font-weight:600} .approve{background:#16a34a;color:#fff} .dismiss{background:#e5e7eb}
</style></head><body><main>
<h1>Regulatory changes waiting for review</h1>
<div class="muted">${queue.length} brief(s). Briefs are written by AI and checked by code. They are not legal advice: confirm against the source before approving.</div>
${cards || '<div class="card">Nothing to review.</div>'}
</main></body></html>`;
return [{ json: { html } }];
