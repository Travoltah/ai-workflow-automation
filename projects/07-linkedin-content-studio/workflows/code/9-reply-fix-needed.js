// NODE: "Reply fix needed?"  (Code node, mode: Run Once for Each Item)
const d = $('Read reply').item.json;
const lint = $json;
const errors = d.reply && Array.isArray(lint.errors) ? lint.errors : [];
return { json: { ...d, errors, needsFix: !d.failed && errors.length > 0 } };
