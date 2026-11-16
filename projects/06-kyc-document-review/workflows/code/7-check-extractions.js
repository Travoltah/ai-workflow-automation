// NODE: "Check extractions"  (Code node, mode: Run Once for All Items)
// The model reads; the code checks what it can before anything is stored:
//   - dates must be real YYYY-MM-DD dates, or they are dropped (and noted)
//   - for files with digital text, the name, address and statement date the model read must appear in
//     that text; if not, the field is marked unverified for the reviewer
//   - a failed, refused or cut-off call is stored as "unreadable", never as data
// The deterministic KYC checks (MRZ check digits, expiry, age, matching) run afterwards in the intake service.
const settings = $('Settings').first().json;
const inputs = $('Get page images').all().map((i) => i.json);
const responses = $input.all().map((i) => i.json);
const PRICES = { 'claude-opus-5-5': [4, 20], 'claude-haiku-5-5': [0.1, 0.5] };      // USD per million tokens
const DATE_FIELDS = ['date_of_birth', 'issue_date', 'expiry_date', 'document_date'];
const norm = (s) => String(s || '').toLowerCase().normalize('NFKD').replace(/[^a-z0-9]+/g, ' ').trim();
const isDate = (s) => /^\d{4}-\d{2}-\d{2}$/.test(s) && new Date(`${s}T00:00:00Z`).toISOString().slice(0, 10) === s;

let total = 0;
const problems = [];
const extractions = inputs.map((input, i) => {
  const res = responses[i] || {};
  const unverified = [];
  const u = res.usage || {};                                       // counted even when the answer is unusable
  const inTok = (u.input_tokens || 0) + (u.cache_read_input_tokens || 0) + (u.cache_creation_input_tokens || 0);
  const [pin, pout] = PRICES[settings.model] || PRICES['claude-opus-5-5'];
  const cost = Math.round(((inTok * pin + (u.output_tokens || 0) * pout) / 1e6) * 10000) / 10000;
  total += cost;
  let e = null;
  if (res.error) problems.push(`${input.filename}: call failed (${String(res.error.description || res.error.message || '').slice(0, 160)})`);
  else if (res.stop_reason !== 'end_turn') problems.push(`${input.filename}: answer incomplete (${res.stop_reason})`);
  else {
    try { e = JSON.parse(res.content.find((b) => b.type === 'text').text); } catch (err) { problems.push(`${input.filename}: invalid JSON`); }
  }
  if (!e) {
    // Store nothing: the document stays "not read yet", the application stays "processing", and a re-run
    // (POST /webhook/kyc/process) reads it again. A failed call must never look like a wrong document.
    return null;
  }
  {
    for (const [k, f] of Object.entries(e.fields)) {                // "" means "not on the document"
      e.fields[k] = { value: f.value?.trim() ? f.value.trim() : null, as_printed: f.as_printed?.trim() ? f.as_printed.trim() : null, confidence: f.confidence };
    }
    for (const f of DATE_FIELDS) {
      const v = e.fields[f]?.value;
      if (v && !isDate(v)) { unverified.push(`${f} "${v}" is not a real date and was dropped`); e.fields[f] = { ...e.fields[f], value: null, confidence: 'low' }; }
    }
    if (input.text && input.text.length > 40) {                  // a digital document: check the reading against its text
      const text = norm(input.text);
      for (const f of ['full_name', 'address', 'issuer']) {
        const printed = e.fields[f]?.as_printed;
        if (printed && !text.includes(norm(printed))) unverified.push(`${f} "${printed}" was not found in the document's text`);
      }
      const dp = e.fields.document_date?.as_printed;
      if (dp && !text.includes(norm(dp))) unverified.push(`document_date "${dp}" was not found in the document's text`);
    }
  }
  return {
    document_id: input.document_id, model: settings.model, doc_type: e.doc_type, readability: e.readability, fields: e.fields, notes: e.notes,
    verification: { unverified, digital_text_checked: Boolean(input.text && input.text.length > 40) },
    usage: { input_tokens: inTok, output_tokens: u.output_tokens || 0 }, cost_usd: cost,
  };
}).filter(Boolean);
return [{ json: { extractions, calls: inputs.length, problems, cost_usd: Math.round(total * 10000) / 10000 } }];
