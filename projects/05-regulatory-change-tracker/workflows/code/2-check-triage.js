// NODE: "Check triage"  (Code node, mode: Run Once for All Items)
// Every change must be classified exactly once. Fail-safe: a change the triage missed, or a triage
// call that failed, counts as RELEVANT, because missing a real change is worse than reviewing a dull one.

const plan = $('Plan triage').first().json;
const response = $input.first().json;
const problems = [];
let parsed = null;

if (response.error) problems.push(`Triage call failed: ${JSON.stringify(response.error).slice(0, 200)}`);
else if (response.stop_reason !== 'end_turn') problems.push(`Triage answer incomplete (${response.stop_reason})`);
else {
  try { parsed = JSON.parse(response.content.find((b) => b.type === 'text').text); }
  catch (e) { problems.push(`Triage answer was not valid JSON: ${e.message}`); }
}

const byId = new Map();
for (const item of parsed?.items || []) {
  if (!plan.changeIds.includes(item.change_id)) { problems.push(`Triage for an unknown change ${item.change_id}`); continue; }
  if (byId.has(item.change_id)) { problems.push(`Change ${item.change_id} classified twice; kept the first`); continue; }
  byId.set(item.change_id, item);
}

const triage = plan.changeIds.map((id) => {
  const t = byId.get(id);
  if (!t) problems.push(`Change ${id} was not classified; treated as relevant to be safe`);
  return t
    ? { change_id: id, relevant: t.relevant, triage: { ...t, source: 'model' } }
    : { change_id: id, relevant: true, triage: { change_id: id, relevant: true, topics: [], reason: 'Not classified by the triage step; sent to analysis to be safe.', source: 'fail-safe' } };
});

return [{ json: { triage, problems, usage: response.usage || null } }];
