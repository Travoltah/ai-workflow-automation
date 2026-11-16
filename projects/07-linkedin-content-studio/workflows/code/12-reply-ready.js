// NODE: "Reply ready"  (Code node, mode: Run Once for Each Item)
const d = $json;
const body = d.failed
  ? { event: 'failed', stage: 'draft', error: d.error }
  : { event: 'drafted', reply: d.reply, note: d.note, shouldLike: d.shouldLike, costUsd: d.cost };
return { json: { id: d.id, body } };
