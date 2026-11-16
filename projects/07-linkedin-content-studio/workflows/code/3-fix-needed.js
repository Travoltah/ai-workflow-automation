// NODE: "Fix needed?"  (Code node, mode: Run Once for Each Item)
// The website's style check ran on the draft. Problems that would block approval go back to Claude once.
const d = $('Read draft').item.json;
const lint = $json;
const errors = Array.isArray(lint.errors) ? lint.errors : [];
return { json: { ...d, lint: { ok: lint.ok === true, errors, warnings: lint.warnings || [] }, needsFix: !d.failed && errors.length > 0 } };
