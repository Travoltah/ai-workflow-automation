// NODE: "List sources"  (Code node, mode: Run Once for All Items)
// One item per source due for a check, so "Collect source" calls the collector once per source.
// When nothing is due, one item with source_id null: the collector answers "none" and the run still finishes.
const run = $input.first().json.run;                // reg.start_run()
const items = run.sources.map((s) => ({ json: { run_id: run.run_id, source_id: s.source_id, code: s.code } }));
return items.length ? items : [{ json: { run_id: run.run_id, source_id: null, code: null } }];
