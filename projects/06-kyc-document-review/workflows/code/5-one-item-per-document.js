// NODE: "One item per document to read"  (Code node, mode: Run Once for All Items)
// One item per readable, not-yet-read document; or a single "skip" item when there is nothing to read.
const appId = ($('Intake results').isExecuted ? $('Intake results') : $('Read process request')).first().json.application_id;
const docs = $input.first().json.docs || [];
return docs.length
  ? docs.map((d) => ({ json: { application_id: appId, ...d, skip: false } }))
  : [{ json: { application_id: appId, skip: true } }];
