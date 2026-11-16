"""Evaluates the data quality monitor end to end against planted defects.

Three runs through the workflow's API, each graded against the answer key that
scripts/generate_data.py writes (evaluation/planted-defects.json):

  0. Rule tests    evaluation/rule-edge-cases.sql: boundary cases for the trickiest rules (pure SQL, no AI)
     Guardrail     evaluation/test-check-explanations.js: the explanation check against a real Claude response
  1. Defect data   every planted defect must be caught with exactly the right record ids (no misses,
                   no extras); every explanation must pass the workflow's own check; the likely cause
                   must name a plausible root cause (keyword check); a Jira ticket per incident.
  2. Same data     nothing new: every incident is "ongoing", no AI call, no cost.
  3. Clean data    no rule may fail (false alarms), and every incident must be resolved.

Writes results/<timestamp>.md and .csv, and exits with code 1 when a quality gate fails (for CI).

    python evaluation/evaluate.py --url http://localhost:5678/webhook/dq/run --pg-container dq-postgres

Loads data with `docker exec -i <container> psql`, so Docker must be able to reach the database container.
Standard library only (Python 3.9+).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

GATES = {
    "detection_recall": 1.0,       # every planted defect found, with exactly the right record ids
    "false_alarms": 0,             # rules failing on clean data, plus unexpected failures on defect data
    "explanation_check_rate": 1.0, # explanations that passed the workflow's own check
    "cause_accuracy": 0.8,         # likely cause names a plausible root cause (keyword check)
    "max_cost_usd": 1.0,           # per run
}


def load(container: str, user: str, db: str, clean: bool, keep_history: bool):
    args = [sys.executable, str(ROOT / "scripts" / "generate_data.py"), "--out", str(ROOT / "data" / "eval-seed.sql")]
    if clean:
        args.append("--clean")
    if keep_history:
        args.append("--keep-history")
    subprocess.run(args, check=True, capture_output=True)
    with open(ROOT / "data" / "eval-seed.sql", "rb") as f:
        subprocess.run(["docker", "exec", "-i", container, "psql", "-U", user, "-d", db, "-q", "-v", "ON_ERROR_STOP=1"],
                       stdin=f, check=True, capture_output=True)


def run(url: str, trigger: str) -> tuple[dict, float]:
    req = urllib.request.Request(url, data=json.dumps({"trigger": trigger}).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.loads(r.read()), time.time() - t0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://localhost:5678/webhook/dq/run")
    ap.add_argument("--pg-container", default="dq-postgres")
    ap.add_argument("--pg-user", default="postgres")
    ap.add_argument("--db", default="contoso_dq")
    a = ap.parse_args()

    print("0/3  rule edge-case tests on clean data…")
    load(a.pg_container, a.pg_user, a.db, clean=True, keep_history=False)
    with open(HERE / "rule-edge-cases.sql", "rb") as f:
        edge = subprocess.run(["docker", "exec", "-i", a.pg_container, "psql", "-U", a.pg_user, "-d", a.db, "-q", "-v", "ON_ERROR_STOP=1"],
                              stdin=f, capture_output=True)
    edge_log = edge.stderr.decode("utf-8", "replace")
    edge_pass, edge_total = edge_log.count("PASS "), 6
    print("     " + "\n     ".join(l.split("NOTICE:  ")[-1].split("ERROR:  ")[-1] for l in edge_log.splitlines() if "PASS" in l or "FAIL" in l))

    print("     guardrail tests (offline, real Claude response)…")
    try:
        guard = subprocess.run(["node", str(HERE / "test-check-explanations.js")], capture_output=True)
        guard_ok, guard_note = guard.returncode == 0, guard.stdout.decode("utf-8", "replace").strip().splitlines()[-1]
    except FileNotFoundError:
        guard_ok, guard_note = True, "skipped (Node.js not installed)"
    print(f"     {guard_note}")

    print("1/3  loading data with planted defects, running the monitor…")
    load(a.pg_container, a.pg_user, a.db, clean=False, keep_history=False)
    key = json.loads((HERE / "planted-defects.json").read_text(encoding="utf-8"))["defects"]
    r1, t1 = run(a.url, "eval-defects")
    print("2/3  same data again…")
    r2, t2 = run(a.url, "eval-repeat")
    print("3/3  clean data…")
    load(a.pg_container, a.pg_user, a.db, clean=True, keep_history=True)
    r3, t3 = run(a.url, "eval-clean")

    got = {f["rule_code"]: f for f in r1["failures"]}
    rows, found, causes, checked = [], 0, 0, 0
    for d in key:
        f = got.get(d["rule_code"])
        ids_ok = bool(f) and sorted(f["record_ids"]) == d["expected_record_ids"]
        e = (f or {}).get("explanation") or {}
        text = f"{e.get('likely_cause', '')} {e.get('suggested_fix', '')}".lower()
        hit = [k for k in d["cause_keywords"] if k in text]
        ok_check = bool(f) and f.get("explanation_ok") is True
        found += ids_ok
        causes += bool(hit) and ok_check
        checked += ok_check
        rows.append({"rule_code": d["rule_code"], "defect": d["defect"], "caught_exactly": ids_ok,
                     "expected_ids": len(d["expected_record_ids"]), "reported_ids": len((f or {}).get("record_ids", [])),
                     "explanation_check": ok_check, "cause_keywords_matched": ", ".join(hit), "jira": (f or {}).get("jira_key") or "",
                     "likely_cause": e.get("likely_cause", "")})
    n = len(key)
    unexpected = sorted(set(got) - {d["rule_code"] for d in key})
    m = {
        "detection_recall": found / n,
        "false_alarms": len(unexpected) + r3["checks_failed"],
        "explanation_check_rate": checked / n,
        "cause_accuracy": causes / n,
        "tickets_created": sum(1 for x in rows if x["jira"]),
        "repeat_new": r2["new_incidents"], "repeat_ongoing": r2["ongoing_incidents"], "repeat_cost": float(r2["usage"]["cost_usd"] or 0),
        "clean_failed": r3["checks_failed"], "clean_resolved": r3["resolved_incidents"],
        "cost_usd": float(r1["usage"]["cost_usd"] or 0), "input_tokens": r1["usage"]["input_tokens"], "output_tokens": r1["usage"]["output_tokens"],
        "seconds": [round(t1), round(t2), round(t3)],
    }
    gates = [
        ("Rule edge-case tests (SQL)", edge.returncode == 0 and edge_pass == edge_total, f"{edge_pass}/{edge_total}"),
        ("Guardrail tests (offline, real Claude response)", guard_ok, guard_note),
        ("Detection recall (exact record ids)", m["detection_recall"] >= GATES["detection_recall"], f"{found}/{n}"),
        ("False alarms (unexpected + clean-data failures)", m["false_alarms"] <= GATES["false_alarms"], str(m["false_alarms"])),
        ("Explanations passing the code check", m["explanation_check_rate"] >= GATES["explanation_check_rate"], f"{checked}/{n}"),
        ("Likely cause names a plausible root cause", m["cause_accuracy"] >= GATES["cause_accuracy"], f"{causes}/{n} ({m['cause_accuracy']:.0%})"),
        ("Jira ticket per incident", m["tickets_created"] == n, f"{m['tickets_created']}/{n}"),
        ("Repeat run: no new incidents, all ongoing, no AI cost",
         m["repeat_new"] == 0 and m["repeat_ongoing"] == n and m["repeat_cost"] == 0, f"new {m['repeat_new']}, ongoing {m['repeat_ongoing']}, ${m['repeat_cost']:.2f}"),
        ("Clean data: every incident resolved", m["clean_resolved"] == n and m["clean_failed"] == 0, f"resolved {m['clean_resolved']}, failed {m['clean_failed']}"),
        ("Cost of the explaining run", m["cost_usd"] <= GATES["max_cost_usd"], f"${m['cost_usd']:.4f}"),
    ]

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    with open(out / f"{stamp}.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    md = [f"# Evaluation {stamp}", "", f"Model: {r1['usage']['model']} · tokens {m['input_tokens']:,} in / {m['output_tokens']:,} out · "
          f"cost ${m['cost_usd']:.4f} · run times {m['seconds'][0]} s / {m['seconds'][1]} s / {m['seconds'][2]} s", "",
          "| Gate | Result | Value |", "|---|---|---|"]
    md += [f"| {g} | {'PASS' if ok else 'FAIL'} | {v} |" for g, ok, v in gates]
    md += ["", "| Rule | Planted defect | Caught exactly | Check | Cause keywords | Jira |", "|---|---|---|---|---|---|"]
    md += [f"| {x['rule_code']} | {x['defect']} | {'yes' if x['caught_exactly'] else 'NO'} ({x['reported_ids']}/{x['expected_ids']}) | "
           f"{'passed' if x['explanation_check'] else 'FAILED'} | {x['cause_keywords_matched'] or '—'} | {x['jira']} |" for x in rows]
    md += ["", "## AI run summary", "", r1.get("ai_summary", "")]
    (out / f"{stamp}.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print()
    for g, ok, v in gates:
        print(f"  {'PASS' if ok else 'FAIL'}  {g}: {v}")
    print(f"\nReport: {out / (stamp + '.md')}")
    return 0 if all(ok for _, ok, _ in gates) else 1


if __name__ == "__main__":
    sys.exit(main())
