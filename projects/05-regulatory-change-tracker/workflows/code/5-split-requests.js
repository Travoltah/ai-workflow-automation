// NODE: "One item per brief"  (Code node, mode: Run Once for All Items)
// Turns the planned requests into one item each, so "Write brief" calls Claude once per change.
return $input.first().json.requests.map((r) => ({ json: r }));
