"""Evaluates the regulatory change tracker end to end against the mock regulators' planted changes.

  0. Offline      collector unit tests (pytest, in the collector container) and the brief guardrail tests
                  (node evaluation/test-verify-briefs.js, a real Claude response); no AI cost
  1. Day 1        reset, baseline run: every source recorded, 0 changes, no AI call
  2. Day 2        10 planted changes in 5 markets: detection, the failing source, triage (incl. a
                  prompt-injection attempt), briefs (deadlines, required controls, priority) and an
                  independent re-check that every stored quote is in the source document
  3. Day 2 again  nothing new: 0 changes, no AI call
  4. Review       approve one change (one Jira task per control), dismiss one (no tasks), and a
                  second decision on the same change must be refused

Writes results/<timestamp>.md and exits 1 when a quality gate fails. RESETS the tracker's data.

    python evaluation/evaluate.py --url http://localhost:5678/webhook --pg-container reg-postgres \
        --collector-container reg-collector --mock-url http://localhost:8090
Standard library only (Python 3.9+).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def post(url: str, body: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.loads(r.read())


def psql(a, sql: str) -> str:
    return subprocess.run(["docker", "exec", "-i", a.pg_container, "psql", "-U", a.pg_user, "-d", "reg_tracker", "-tA", "-v", "ON_ERROR_STOP=1"],
                          input=sql.encode(), capture_output=True, check=True).stdout.decode("utf-8")


def scenario(a, name: str):
    if a.mock_container:   # mock server without a published port: switch from inside its container
        subprocess.run(["docker", "exec", a.mock_container, "python", "-c",
                        f"import urllib.request; urllib.request.urlopen('http://localhost:8090/_scenario?name={name}')"], check=True)
    else:
        urllib.request.urlopen(f"{a.mock_url}/_scenario?name={name}", timeout=30).read()


def norm(s: str) -> str:
    s = str(s or "").lower().replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s.replace("–", "-").replace("—", "-")).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://localhost:5678/webhook", help="n8n webhook base URL")
    ap.add_argument("--pg-container", default="reg-postgres")
    ap.add_argument("--pg-user", default="postgres")
    ap.add_argument("--collector-container", default="reg-collector")
    ap.add_argument("--mock-url", default="http://localhost:8090")
    ap.add_argument("--mock-container", default="", help="switch scenarios with docker exec instead of --mock-url")
    a = ap.parse_args()
    golden = json.loads((HERE / "golden.json").read_text(encoding="utf-8"))
    gates = []

    print("0/4  offline tests…")
    unit = subprocess.run(["docker", "exec", a.collector_container, "python", "-m", "pytest", "-q", "tests"], capture_output=True)
    unit_line = unit.stdout.decode().strip().splitlines()[-1] if unit.stdout else "no output"
    gates.append(("Collector unit tests", unit.returncode == 0, unit_line))
    try:
        guard = subprocess.run(["node", str(HERE / "test-verify-briefs.js")], capture_output=True)
        gates.append(("Brief guardrail tests (real Claude response)", guard.returncode == 0, guard.stdout.decode().strip().splitlines()[-1]))
    except FileNotFoundError:
        gates.append(("Brief guardrail tests (real Claude response)", True, "skipped: Node.js not installed"))

    print("1/4  reset + day-1 baseline…")
    psql(a, (HERE / "reset.sql").read_text(encoding="utf-8").replace("\\connect reg_tracker", ""))
    scenario(a, "day1")
    r1 = post(f"{a.url}/reg/run", {"trigger": "eval-day1", "force": True})
    gates.append(("Day 1: every source is a baseline, 0 changes, $0",
                  all(s["status"] == "baseline" for s in r1["source_checks"]) and r1["changes_detected"] == 0 and r1["cost_usd"] == 0,
                  f"{sum(s['status'] == 'baseline' for s in r1['source_checks'])}/{len(r1['source_checks'])} baselines, {r1['changes_detected']} changes, ${r1['cost_usd']:.2f}"))

    print("2/4  day 2: planted changes…")
    scenario(a, "day2")
    r2 = post(f"{a.url}/reg/run", {"trigger": "eval-day2", "force": True})
    changes = r2["changes"]
    find = lambda g: [c for c in changes if c["jurisdiction"] == g["jurisdiction"] and g["title_contains"].lower() in c["title"].lower()]
    rows, detected, triage_ok, dates_ok, controls_got, controls_req, prio_ok = [], 0, 0, 0, 0, 0, 0
    relevant_golden = [g for g in golden["changes"] if g["relevant"]]
    for g in golden["changes"]:
        m = find(g)
        c = m[0] if len(m) == 1 else None
        detected += bool(c) and c["change_type"] == g["change_type"]
        t_ok = bool(c) and bool(c["relevant"]) == g["relevant"]
        triage_ok += t_ok
        row = {"market": g["jurisdiction"], "change": g["title_contains"], "detected": bool(c), "triage": "ok" if t_ok else "WRONG",
               "status": c["status"] if c else "", "dates": "", "controls": "", "priority": ""}
        if g["relevant"] and c:
            b = c.get("brief") or {}
            got_dates = {k["date"] for k in b.get("key_dates", [])}
            d_ok = all(d in got_dates for d in g["dates"])
            dates_ok += d_ok
            mapped = {x["control_id"] for x in b.get("affected_controls", [])}
            hit = [x for x in g["required_controls"] if x in mapped]
            controls_got += len(hit); controls_req += len(g["required_controls"])
            prio_ok += c.get("priority") == g["priority"]
            row.update(dates=("ok " if d_ok else "MISSING ") + ", ".join(sorted(got_dates)),
                       controls=f"{len(hit)}/{len(g['required_controls'])} required · " + ", ".join(sorted(mapped)),
                       priority=f"{c.get('priority')} (expected {g['priority']})")
        rows.append(row)
    extra = len(changes) - sum(len(find(g)) for g in golden["changes"])
    failing = sorted(s["code"] for s in r2["source_checks"] if s["status"] == "error")
    inj = [g for g in golden["changes"] if g.get("injection")][0]
    inj_ok = bool(find(inj)) and find(inj)[0]["relevant"] is True

    # independent quote check: every quote stored in a brief must be in its document, word for word
    texts = json.loads(psql(a, f"SELECT json_object_agg(c.change_id, d.current_text || E'\\n' || c.diff_text) FROM reg.changes c JOIN reg.documents d USING (doc_id) WHERE c.run_id = {r2['run_id']}") or "{}")
    quotes = [(c["change_id"], q) for c in changes if c.get("brief") for q in
              [k["quote"] for k in c["brief"].get("key_dates", [])] + [o["quote"] for o in c["brief"].get("obligations", [])]]
    bad_quotes = [q for cid, q in quotes if norm(q) not in norm(texts.get(str(cid), ""))]

    gates += [
        ("Day 2: every planted change detected (right type, no extras)", detected == len(golden["changes"]) and extra == 0, f"{detected}/{len(golden['changes'])}, {extra} extra"),
        ("Day 2: failing source reported", failing == golden["source_errors"], ", ".join(failing) or "none"),
        ("Triage correct (relevant kept, noise dropped)", triage_ok >= len(golden["changes"]) - 1, f"{triage_ok}/{len(golden['changes'])}"),
        ("Triage recall on relevant changes", all(r["triage"] == "ok" for r, g in zip(rows, golden["changes"]) if g["relevant"]), f"{sum(r['triage'] == 'ok' for r, g in zip(rows, golden['changes']) if g['relevant'])}/{len(relevant_golden)}"),
        ("Prompt injection resisted", inj_ok, "relevant" if inj_ok else "classified as told"),
        ("Every stored quote found in its document (independent check)", not bad_quotes, f"{len(quotes) - len(bad_quotes)}/{len(quotes)}"),
        ("Deadlines found", dates_ok >= len(relevant_golden) - 1, f"{dates_ok}/{len(relevant_golden)}"),
        ("Required controls mapped", controls_req and controls_got / controls_req >= 0.8, f"{controls_got}/{controls_req}"),
        ("Priority from the company profile", prio_ok >= len(relevant_golden) - 1, f"{prio_ok}/{len(relevant_golden)}"),
        ("Cost of the day-2 run", r2["cost_usd"] <= 1.0, f"${r2['cost_usd']:.4f}"),
    ]

    print("3/4  day 2 again…")
    r3 = post(f"{a.url}/reg/run", {"trigger": "eval-repeat", "force": True})
    gates.append(("Repeat run: nothing new, no AI call", r3["changes_detected"] == 0 and r3["cost_usd"] == 0, f"{r3['changes_detected']} changes, ${r3['cost_usd']:.2f}"))

    print("4/4  review decisions…")
    approve_c = find(golden["changes"][1])[0]
    dismiss_c = find(golden["changes"][2])[0]
    d1 = post(f"{a.url}/reg/decide", {"change_id": approve_c["change_id"], "decision": "approve", "reviewer": "Evaluation", "note": "eval"})
    d2 = post(f"{a.url}/reg/decide", {"change_id": dismiss_c["change_id"], "decision": "dismiss", "reviewer": "Evaluation", "note": "eval"})
    d3 = post(f"{a.url}/reg/decide", {"change_id": approve_c["change_id"], "decision": "approve", "reviewer": "Evaluation", "note": "again"})
    n_controls = len((approve_c.get("brief") or {}).get("affected_controls", []))
    keyed = [t for t in d1.get("tasks", []) if t.get("jira_key")]
    gates += [
        ("Approve: one Jira task per affected control", d1["ok"] and len(keyed) == n_controls > 0, f"{len(keyed)}/{n_controls} tasks with Jira keys"),
        ("Dismiss: no tasks", d2["ok"] and not d2["tasks"], f"{len(d2.get('tasks', []))} tasks"),
        ("A second decision is refused", d3["ok"] is False, d3.get("error") or "accepted"),
    ]

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = HERE / "results"; out.mkdir(exist_ok=True)
    md = [f"# Evaluation {stamp}", "", f"Day-2 run: ${r2['cost_usd']:.4f} · usage {json.dumps(r2['usage'])}", "",
          "| Gate | Result | Value |", "|---|---|---|"] + [f"| {g} | {'PASS' if ok else 'FAIL'} | {v} |" for g, ok, v in gates]
    md += ["", "| Market | Planted change | Detected | Triage | Status | Dates | Controls | Priority |", "|---|---|---|---|---|---|---|---|"]
    md += [f"| {r['market']} | {r['change']} | {'yes' if r['detected'] else 'NO'} | {r['triage']} | {r['status']} | {r['dates']} | {r['controls']} | {r['priority']} |" for r in rows]
    if bad_quotes:
        md += ["", "## Quotes not found", *[f"- {q}" for q in bad_quotes]]
    (out / f"{stamp}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print()
    for g, ok, v in gates:
        print(f"  {'PASS' if ok else 'FAIL'}  {g}: {v}")
    print(f"\nReport: {out / (stamp + '.md')}")
    return 0 if all(ok for _, ok, _ in gates) else 1


if __name__ == "__main__":
    sys.exit(main())
