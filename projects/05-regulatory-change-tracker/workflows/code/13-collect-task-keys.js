// NODE: "Collect task keys"  (Code node, mode: Run Once for All Items)
// Pairs each Jira response with its task, so the keys are stored against the right control.
const planned = $('Plan Jira tasks').all();
const keys = [];
const failures = [];
$input.all().forEach((item, i) => {
  const req = planned[item.pairedItem?.item ?? i]?.json || {};
  if (item.json.error) failures.push(`task ${req.task_id}: ${JSON.stringify(item.json.error).slice(0, 200)}`);
  else if (item.json.key) keys.push({ task_id: req.task_id, jira_key: item.json.key });
});
return [{ json: { keys, failures } }];
