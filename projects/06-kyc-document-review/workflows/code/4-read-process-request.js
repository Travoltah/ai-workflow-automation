// NODE: "Read process request"  (Code node, mode: Run Once for All Items)
// POST /webhook/kyc/process { application_id }: called by the intake service after a password unlocks
// a file, or by hand to re-run an application. Reads any documents not read yet, then re-runs the checks.
const id = parseInt(($input.first().json.body || {}).application_id, 10);
if (!id) throw new Error('application_id is required');
return [{ json: { application_id: id, intake: [] } }];
