// NODE: "Build review page"  (Code node, mode: Run Once for All Items)
// The reviewer's screen: each application with its document images, the fields the AI read, every check,
// what the customer must fix, a password box for protected files, and the decision buttons.
// The password form posts to the INTAKE SERVICE, not to n8n, so passwords never enter workflow data.
const s = $('Settings').first().json;
const queue = $input.first().json.queue || [];
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const tone = { ready_for_review: 'good', action_required: 'warn', processing: 'note', approved: 'good', rejected: 'bad', documents_requested: 'warn',
  ok: 'good', needs_password: 'warn', poor_quality: 'bad', unsupported_type: 'bad', rejected_macro: 'bad', corrupt: 'bad', password_locked: 'bad',
  fail: 'bad', warn: 'warn', pass: 'good' };
const badge = (t, k = t) => `<span class="badge ${tone[k] || ''}">${esc(String(t).replace(/_/g, ' '))}</span>`;
const KEY = ['full_name', 'date_of_birth', 'document_number', 'issuing_country', 'expiry_date', 'address', 'document_date', 'issuer', 'mrz_line1', 'mrz_line2'];

const doc = (d) => {
  const f = d.fields || {};
  const rows = KEY.filter((k) => f[k]?.value || f[k]?.as_printed).map((k) =>
    `<tr><td>${esc(k.replace(/_/g, ' '))}</td><td class="${k.startsWith('mrz') ? 'mono' : ''}">${esc(f[k].as_printed ?? f[k].value)}</td><td>${esc(f[k].value !== f[k].as_printed ? f[k].value : '')}</td><td>${f[k].confidence === 'low' ? badge('low', 'warn') : esc(f[k].confidence)}</td></tr>`).join('');
  return `<div class="doc">
  <div class="thumbs">${(d.thumbs || []).map((t) => `<img src="data:image/jpeg;base64,${t}" alt="">`).join('') || '<div class="noimg">no image</div>'}</div>
  <div class="docinfo">
    <div class="head"><b>${esc(d.filename)}</b>${badge(d.status)}${d.doc_type ? badge(d.doc_type.replace('_', ' '), 'note') : ''}${d.encryption === 'password' ? badge('was password-protected', 'note') : ''}${d.scanned ? badge('scan / photo', '') : badge('digital', '')}</div>
    <div class="muted">uploaded as ${esc(d.declared_type)} · ${esc(d.mime || 'unknown type')}</div>
    ${d.status_reason ? `<p class="warnline">${esc(d.status_reason)}</p>` : ''}
    ${d.status === 'needs_password' ? `<form method="post" action="${esc(s.unlockUrl)}" autocomplete="off" class="unlock">
      <input type="hidden" name="document_id" value="${d.document_id}"><input name="actor" placeholder="Your name" required>
      <input type="password" name="password" placeholder="Password from the customer" autocomplete="new-password" required>
      <button>Open file</button><span class="muted">The password is used once by the intake service and never stored.</span></form>` : ''}
    ${rows ? `<table><tr><th>Field</th><th>As printed</th><th>Normalised</th><th>Confidence</th></tr>${rows}</table>` : ''}
    ${d.notes ? `<p class="muted">AI notes: ${esc(d.notes)}</p>` : ''}
  </div></div>`;
};

const cards = queue.map((a) => {
  const fails = a.checks.filter((c) => c.result !== 'pass');
  const passes = a.checks.filter((c) => c.result === 'pass');
  return `<div class="card">
  <div class="head"><h2>${esc(a.reference)}</h2>${badge(a.status)}${a.decision ? badge(`decided: ${a.decision} by ${a.reviewed_by}`, 'note') : ''}</div>
  <div class="muted">Application #${a.application_id} · ${esc(a.applicant.full_name)} · born ${esc(a.applicant.date_of_birth)} · ${esc(a.applicant.address)}</div>
  ${(a.customer_actions || []).length ? `<div class="actions"><b>The customer must:</b><ul>${a.customer_actions.map((x) => `<li>${esc(x)}</li>`).join('')}</ul></div>` : ''}
  ${a.documents.map(doc).join('')}
  <h3>Checks</h3>
  <ul class="checks">${fails.map((c) => `<li>${badge(c.result)} <b>${esc(c.code)}</b> ${esc(c.detail)}</li>`).join('')}
  ${passes.length ? `<li class="muted">${passes.length} passed: ${esc(passes.map((c) => c.code).join(', '))}</li>` : ''}</ul>
  ${a.decision ? '' : `<form method="post" action="${esc(s.decideUrl)}" class="decide">
    <input type="hidden" name="application_id" value="${a.application_id}"><input name="reviewer" placeholder="Your name" required>
    <input name="note" placeholder="Note" size="40">
    ${a.status === 'ready_for_review' ? '<button name="decision" value="approve" class="approve">Approve</button>' : ''}
    <button name="decision" value="request_documents">Request documents</button>
    <button name="decision" value="reject" class="reject">Reject</button></form>`}
</div>`;
}).join('');

const html = `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>KYC review</title>
<style>
  body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#f4f6fb;color:#1f2937}
  main{max-width:1150px;margin:0 auto;padding:24px 16px 48px} h1{font-size:22px;margin:0 0 4px} h2{font-size:17px;margin:0} h3{font-size:14px;margin:14px 0 6px}
  .muted{color:#6b7280;font-size:12px} .card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:16px;margin:16px 0}
  .head{display:flex;flex-wrap:wrap;gap:6px;align-items:center} .badge{font-size:12px;padding:2px 9px;border-radius:999px;background:#eef2ff;color:#3730a3}
  .badge.bad{background:#fee2e2;color:#991b1b} .badge.warn{background:#ffedd5;color:#9a3412} .badge.good{background:#dcfce7;color:#166534} .badge.note{background:#e0f2fe;color:#075985}
  .doc{display:grid;grid-template-columns:300px 1fr;gap:14px;border-top:1px solid #f0f1f4;padding-top:12px;margin-top:12px}
  .thumbs img{width:100%;border:1px solid #e5e7eb;border-radius:6px;margin-bottom:6px} .noimg{height:120px;display:grid;place-items:center;background:#f3f4f6;color:#9ca3af;border-radius:6px}
  table{border-collapse:collapse;font-size:12px;width:100%;margin-top:6px} th,td{text-align:left;padding:4px 6px;border-bottom:1px solid #eef0f3} th{background:#f9fafb}
  .mono{font-family:Consolas,monospace;font-size:11px;word-break:break-all} .warnline{color:#9a3412;font-size:13px;margin:6px 0}
  .actions{background:#fff7ed;border:1px solid #fed7aa;border-radius:8px;padding:8px 12px;margin-top:10px;font-size:13px} .actions ul{margin:4px 0 0 18px;padding:0}
  .checks{list-style:none;padding:0;margin:0;font-size:13px} .checks li{margin:4px 0}
  form{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:10px} input{padding:6px 8px;border:1px solid #d1d5db;border-radius:6px}
  button{padding:7px 12px;border-radius:6px;border:0;cursor:pointer;font-weight:600;background:#e5e7eb} .approve{background:#16a34a;color:#fff} .reject{background:#dc2626;color:#fff}
  .unlock{background:#f0f9ff;padding:8px;border-radius:8px}
  @media(max-width:760px){.doc{grid-template-columns:1fr}}
</style></head><body><main>
<h1>KYC applications</h1>
<div class="muted">Fields are read by AI and checked by code (MRZ check digits, dates, expiry, age, matching). A person makes every decision. Specimen documents only in this demo.</div>
${cards || '<div class="card">No applications yet.</div>'}
</main></body></html>`;
return [{ json: { html } }];
