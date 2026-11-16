// NODE: "One item per upload"  (Code node, mode: Run Once for All Items)
// One item per file, so "Intake document" sends each to the intake service.
const sub = $('Read submission').first().json;
const applicationId = $input.first().json.application_id;
return sub.documents.map((d) => ({ json: { application_id: applicationId, ...d } }));
