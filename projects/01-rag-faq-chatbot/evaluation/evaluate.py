#!/usr/bin/env python3
"""
Automated evaluation for the RAG FAQ chatbot.

Sends every question in test-cases.csv to the live chat endpoint and measures:
  * Answer accuracy   - in-scope questions answered with all expected facts
  * Citation rate     - answers that name their source document
  * Refusal accuracy  - out-of-scope questions correctly declined (no guessing)
  * Latency           - average and 95th percentile response time

Writes a Markdown + CSV report to evaluation/results/ and exits with code 1 when
the quality gates fail, so it can run in CI after any prompt, model or data change.

Usage:
  python evaluate.py --url http://localhost:5678/webhook/b1d4d570-9e03-5304-9c01-8854082a24ee/chat
  python evaluate.py --url ... --min-accuracy 0.9 --min-refusal 1.0

Standard library only: no pip install needed.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
DEFAULT_URL = "http://localhost:5678/webhook/b1d4d570-9e03-5304-9c01-8854082a24ee/chat"
# Must match the start of the "Reply with fallback" message in the chatbot workflow.
FALLBACK_MARKER = "I couldn't find that in our FAQ"


def ask(url: str, question: str, timeout: float) -> tuple[str, float]:
    """Sends one question in a fresh session (no memory carry-over between test cases)."""
    body = json.dumps({"action": "sendMessage", "sessionId": f"eval-{uuid.uuid4()}", "chatInput": question}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    start = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    elapsed = time.perf_counter() - start
    if isinstance(payload, list):  # some n8n versions wrap the response in a list
        payload = payload[0] if payload else {}
    return str(payload.get("output") or payload.get("text") or ""), elapsed


def grade(case: dict, answer: str) -> dict:
    declined = FALLBACK_MARKER.lower() in answer.lower()
    should_answer = case["should_answer"].strip().lower() == "true"
    keywords = [k.strip() for k in case["expected_keywords"].split("|") if k.strip()]
    missing = [k for k in keywords if k.lower() not in answer.lower()]
    if should_answer:
        passed = not declined and not missing
    else:
        passed = declined
    return {
        "passed": passed,
        "declined": declined,
        "cited": "source:" in answer.lower(),
        "missing": ", ".join(missing),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=DEFAULT_URL, help="Chat Trigger URL (workflow must be active)")
    ap.add_argument("--cases", default=str(HERE / "test-cases.csv"))
    ap.add_argument("--timeout", type=float, default=90)
    ap.add_argument("--min-accuracy", type=float, default=0.85, help="Quality gate for in-scope answers")
    ap.add_argument("--min-refusal", type=float, default=1.0, help="Quality gate for out-of-scope refusals")
    args = ap.parse_args()
    # Windows consoles default to cp1252, which can't print symbols like ≥ or ✅.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    cases =list(csv.DictReader(open(args.cases, encoding="utf-8")))
    rows = []
    for case in cases:
        try:
            answer, secs = ask(args.url, case["question"], args.timeout)
            result = grade(case, answer)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            answer, secs = f"ERROR: {exc}", float("nan")
            result = {"passed": False, "declined": False, "cited": False, "missing": "request failed"}
        rows.append({**case, **result, "seconds": secs, "answer": answer})
        print(f"[{'PASS' if result['passed'] else 'FAIL'}] #{case['id']:>2} {case['question'][:60]:<60} {secs:5.1f}s")

    in_scope = [r for r in rows if r["should_answer"].lower() == "true"]
    out_scope = [r for r in rows if r["should_answer"].lower() != "true"]
    answered = [r for r in in_scope if not r["declined"]]
    latencies = [r["seconds"] for r in rows if r["seconds"] == r["seconds"]]  # drop NaN

    accuracy = sum(r["passed"] for r in in_scope) / max(len(in_scope), 1)
    refusal = sum(r["passed"] for r in out_scope) / max(len(out_scope), 1)
    citation = sum(r["cited"] for r in answered) / max(len(answered), 1)
    avg = statistics.mean(latencies) if latencies else float("nan")
    p95 = sorted(latencies)[int(0.95 * (len(latencies) - 1))] if latencies else float("nan")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    with open(out_dir / f"{stamp}.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    gates_ok = accuracy >= args.min_accuracy and refusal >= args.min_refusal
    report = [
        f"# Evaluation run {stamp}",
        "",
        "| Metric | Result | Gate |",
        "|---|---|---|",
        f"| Answer accuracy (in-scope) | {accuracy:.0%} ({sum(r['passed'] for r in in_scope)}/{len(in_scope)}) | ≥ {args.min_accuracy:.0%} |",
        f"| Refusal accuracy (out-of-scope) | {refusal:.0%} ({sum(r['passed'] for r in out_scope)}/{len(out_scope)}) | ≥ {args.min_refusal:.0%} |",
        f"| Citation rate (answers naming a source) | {citation:.0%} | — |",
        f"| Latency average / p95 | {avg:.1f}s / {p95:.1f}s | — |",
        "",
        f"**Overall: {'PASS ✅' if gates_ok else 'FAIL ❌'}**",
        "",
        "## Failures",
        "",
    ]
    failures = [r for r in rows if not r["passed"]]
    report += [f"- #{r['id']} *{r['question']}*: missing `{r['missing'] or 'expected refusal'}`. Answer: {r['answer'][:200]!r}" for r in failures] or ["None."]
    (out_dir / f"{stamp}.md").write_text("\n".join(report) + "\n", encoding="utf-8")

    print("\n" + "\n".join(report[2:10]))
    print(f"\nReport: {out_dir / (stamp + '.md')}")
    return 0 if gates_ok else 1


if __name__ == "__main__":
    sys.exit(main())
