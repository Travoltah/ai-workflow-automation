// NODE: "Decision response"  (Code node, mode: Run Once for All Items)
const r = $input.first().json.result;              // kyc.decide()
const input = $('Read decision').first().json;
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const html = `<!doctype html><meta charset="utf-8"><title>Decision</title><body style="font-family:system-ui;max-width:620px;margin:40px auto">
${r.ok ? `<h2>Recorded: ${esc(r.decision.replace('_', ' '))} for ${esc(r.reference)}</h2>` : `<h2>Not recorded</h2><p>${esc(r.error)}</p>`}
<p><a href="${esc($('Settings').first().json.reviewUrl)}">Back to the review page</a></p></body>`;
return [{ json: { ...r, html, fromForm: input.fromForm } }];
