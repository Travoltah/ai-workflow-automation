// NODE: "Read submission"  (Code node, mode: Run Once for All Items)
// POST /webhook/kyc/submit with JSON:
//   { reference?, applicant: { full_name, date_of_birth (YYYY-MM-DD), address },
//     documents: [ { filename, declared_type: identity | proof_of_address, data_b64 } ] }
// Checks the shape only; everything about the files themselves is decided by the intake service.
const body = $input.first().json.body || {};
const a = body.applicant || {};
const docs = Array.isArray(body.documents) ? body.documents : [];
const errors = [];
if (!String(a.full_name || '').trim()) errors.push('applicant.full_name is required');
if (!/^\d{4}-\d{2}-\d{2}$/.test(String(a.date_of_birth || ''))) errors.push('applicant.date_of_birth must be YYYY-MM-DD');
if (!docs.length) errors.push('at least one document is required');
if (docs.length > 6) errors.push('at most 6 documents per application');
docs.forEach((d, i) => {
  if (!d.filename || !d.data_b64) errors.push(`documents[${i}] needs filename and data_b64`);
  if (!['identity', 'proof_of_address'].includes(d.declared_type)) errors.push(`documents[${i}].declared_type must be identity or proof_of_address`);
});
if (errors.length) throw new Error(`Invalid submission: ${errors.join('; ')}`);
return [{ json: {
  reference: String(body.reference || `KYC-${Date.now()}`).slice(0, 60),
  applicant: { full_name: String(a.full_name).trim(), date_of_birth: a.date_of_birth, address: String(a.address || '').trim() },
  documents: docs.map((d) => ({ filename: String(d.filename).slice(0, 200), declared_type: d.declared_type, data_b64: d.data_b64 })),
} }];
