"""Evaluates the Jira test-case generator against a fixed set of stories.

Sends every case to the workflow's API, grades the answer, prints a summary and writes
results/<timestamp>.md and .csv. Exits with code 1 when a quality gate fails, so it can run in CI.

    python evaluate.py --url http://localhost:5678/webhook/qa-testgen/generate
    python evaluate.py --only S01,X04          # run a few cases
    python evaluate.py --workers 4             # run cases in parallel (watch your API rate limits)

Standard library only (Python 3.9+).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import datetime as dt
import json
import math
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
STORIES = HERE.parent / "sample-stories" / "stories.json"
CASES = HERE / "test-cases.json"

# USD per million tokens (input, output). Thinking tokens are billed as output.
PRICES = {"claude-opus-5-5": (4.0, 20.0), "claude-haiku-5-5": (0.10, 0.50)}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def load_cases(only: set[str] | None) -> list[dict]:
    stories = {s["id"]: s for s in json.loads(STORIES.read_text(encoding="utf-8"))}
    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    for case in cases:
        story = case["story"]
        if isinstance(story, str):
            story = stories[story]
        case["payload"] = {k: story[k] for k in ("summary", "description", "acceptanceCriteria")}
    return [c for c in cases if not only or c["id"] in only]


def call(url: str, payload: dict, timeout: int) -> tuple[dict | None, str | None, float]:
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        return body, None, time.perf_counter() - started
    except urllib.error.HTTPError as error:
        return None, f"HTTP {error.code}: {error.read().decode('utf-8', 'replace')[:200]}", time.perf_counter() - started
    except Exception as error:  # timeouts, connection refused, invalid JSON
        return None, f"{type(error).__name__}: {error}", time.perf_counter() - started


def grade(case: dict, body: dict | None, error: str | None) -> dict:
    expect = case["expect"]
    expected_status = expect["status"] if isinstance(expect["status"], list) else [expect["status"]]
    row = {"id": case["id"], "expected": "/".join(expected_status), "status": "", "passed": False, "notes": [],
           "tests": 0, "coverage": None, "quality_gate": None, "facts": "", "latency_s": None,
           "input_tokens": 0, "output_tokens": 0, "model": ""}
    if error or not isinstance(body, dict):
        row["notes"].append(error or "Empty response")
        return row

    tests = body.get("testCases", [])
    quality = body.get("quality", {})
    row.update(status=body.get("status", ""), tests=len(tests), coverage=quality.get("coveragePct"),
               quality_gate=quality.get("passed"), latency_s=round(body.get("latencyMs", 0) / 1000, 1),
               input_tokens=(body.get("usage") or {}).get("inputTokens") or 0,
               output_tokens=(body.get("usage") or {}).get("outputTokens") or 0, model=body.get("model", ""))

    ok = row["status"] in expected_status
    if not ok:
        row["notes"].append(f"status {row['status']!r}, expected {row['expected']!r}")

    if "ok" in expected_status:
        if not quality.get("passed"):
            ok = False
            row["notes"].append("workflow quality gate failed: " + "; ".join(quality.get("issues", [])))
        text = json.dumps(tests, ensure_ascii=False).lower()
        groups = expect.get("mustMention", [])
        hits = [any(alt.lower() in text for alt in group) for group in groups]
        row["facts"] = f"{sum(hits)}/{len(groups)}"
        for group, hit in zip(groups, hits):
            if not hit:
                ok = False
                row["notes"].append(f"missing fact: {' | '.join(group)}")
        types = {t.get("type") for t in tests}
        for required in expect.get("requireTypes", []):
            if required not in types:
                ok = False
                row["notes"].append(f"no {required} test")
    else:
        if tests:
            ok = False
            row["notes"].append(f"returned {len(tests)} test cases for an out-of-scope story")

    whole = json.dumps(body, ensure_ascii=False).lower()
    for forbidden in expect.get("mustNotMention", []):
        if forbidden.lower() in whole:
            ok = False
            row["notes"].append(f"forbidden text in answer: {forbidden!r}")

    row["passed"] = ok
    return row


def cost(rows: list[dict]) -> float:
    total = 0.0
    for r in rows:
        price_in, price_out = PRICES.get(r["model"], (0.0, 0.0))
        total += r["input_tokens"] / 1e6 * price_in + r["output_tokens"] / 1e6 * price_out
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://localhost:5678/webhook/qa-testgen/generate")
    parser.add_argument("--only", help="comma-separated case ids, e.g. S01,X04")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=360)
    parser.add_argument("--min-pass", type=float, default=0.85, help="minimum pass rate for in-scope stories")
    parser.add_argument("--min-refusal", type=float, default=1.0, help="minimum pass rate for out-of-scope inputs")
    args = parser.parse_args()

    cases = load_cases(set(args.only.split(",")) if args.only else None)
    print(f"Running {len(cases)} cases against {args.url} with {args.workers} worker(s)...\n")
    rows: list[dict] = []
    with cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(call, args.url, c["payload"], args.timeout): c for c in cases}
        for future in cf.as_completed(futures):
            case = futures[future]
            body, error, seconds = future.result()
            row = grade(case, body, error)
            row["latency_s"] = row["latency_s"] or round(seconds, 1)
            rows.append(row)
            mark = "PASS" if row["passed"] else "FAIL"
            print(f"  {mark}  {row['id']:<4} status={row['status'] or '-':<20} tests={row['tests']:<3} "
                  f"facts={row['facts'] or '-':<4} {row['latency_s']}s  {'; '.join(row['notes'])}")
    rows.sort(key=lambda r: r["id"])

    in_scope = [r for r in rows if r["expected"] == "ok"]
    out_scope = [r for r in rows if r["expected"] != "ok"]
    rate = lambda rs: (sum(r["passed"] for r in rs) / len(rs)) if rs else 1.0
    latencies = [r["latency_s"] for r in rows if r["latency_s"]]
    coverage = [r["coverage"] for r in in_scope if r["coverage"] is not None]
    models = sorted({r["model"] for r in rows if r["model"]})
    summary = {
        "Date": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "Model": ", ".join(models) or "unknown",
        "Cases": len(rows),
        "In-scope pass rate": f"{rate(in_scope):.0%} ({sum(r['passed'] for r in in_scope)}/{len(in_scope)})",
        "Out-of-scope pass rate": f"{rate(out_scope):.0%} ({sum(r['passed'] for r in out_scope)}/{len(out_scope)})",
        "Average AC coverage": f"{statistics.mean(coverage):.1f}%" if coverage else "-",
        "Average test cases per story": f"{statistics.mean([r['tests'] for r in in_scope]):.1f}" if in_scope else "-",
        "Latency avg / p95": (f"{statistics.mean(latencies):.1f}s / {sorted(latencies)[max(0, math.ceil(len(latencies) * 0.95) - 1)]:.1f}s" if latencies else "-"),
        "Estimated cost": f"${cost(rows):.2f} (${cost(rows) / max(1, len(rows)):.3f} per story)",
    }
    gates = [
        ("In-scope pass rate", rate(in_scope) >= args.min_pass, f">= {args.min_pass:.0%}"),
        ("Out-of-scope pass rate", rate(out_scope) >= args.min_refusal, f">= {args.min_refusal:.0%}"),
    ]

    print("\nSummary")
    for key, value in summary.items():
        print(f"  {key:<30} {value}")
    print("\nQuality gates")
    for name, passed, rule in gates:
        print(f"  {'PASS' if passed else 'FAIL'}  {name} {rule}")

    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    fields = ["id", "expected", "status", "passed", "tests", "coverage", "quality_gate", "facts", "latency_s", "input_tokens", "output_tokens", "model", "notes"]
    with open(out_dir / f"{stamp}.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            writer.writerow({**r, "notes": "; ".join(r["notes"])})
    report = ["# Evaluation report", "", "| Metric | Value |", "|---|---|", *[f"| {k} | {v} |" for k, v in summary.items()], "",
              "## Quality gates", "", *[f"- {'PASS' if p else 'FAIL'}: {n} {rule}" for n, p, rule in gates], "",
              "## Cases", "", "| Case | Expected | Status | Pass | Tests | Coverage | Facts | Latency | Notes |", "|---|---|---|---|---|---|---|---|---|",
              *[f"| {r['id']} | {r['expected']} | {r['status']} | {'yes' if r['passed'] else 'no'} | {r['tests']} | {r['coverage'] if r['coverage'] is not None else '-'} | {r['facts'] or '-'} | {r['latency_s']}s | {'; '.join(r['notes']).replace('|', '/')} |" for r in rows]]
    (out_dir / f"{stamp}.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"\nReport: {out_dir / (stamp + '.md')}")
    return 0 if all(p for _, p, _ in gates) else 1


if __name__ == "__main__":
    sys.exit(main())
