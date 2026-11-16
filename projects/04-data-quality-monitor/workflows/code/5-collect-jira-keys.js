// NODE: "Collect Jira keys"  (Code node, mode: Run Once for All Items)
// Pairs each Jira response with the request that produced it, and keeps the keys of new tickets
// so the next run comments on them instead of opening duplicates.
const planned = $('Plan Jira updates').all();
const keys = [];
const failures = [];
$input.all().forEach((item, i) => {
  const req = planned[item.pairedItem?.item ?? i]?.json || {};
  if (item.json.error) failures.push(`${req.rule_code}: ${JSON.stringify(item.json.error).slice(0, 200)}`);
  else if (req.kind === 'create' && item.json.key) keys.push({ incident_id: req.incident_id, jira_key: item.json.key });
});
return [{ json: { keys, failures } }];
