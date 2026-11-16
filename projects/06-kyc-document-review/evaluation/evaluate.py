"""Evaluates the KYC workflow end to end on the specimen applications (sample-documents/cases.json).

  0. Offline     the intake service's unit tests (MRZ, intake, validation) and the extraction guardrail tests
  1. Submit      all 12 applications through POST /webhook/kyc/submit and grade, per application:
                 every file's intake status, the application status, the expected failed / warned checks,
                 no AI call where none is allowed, and the fields read (exact match with the answer key)
  2. Password    C07: a wrong password (refused, counted), then the right one (opened, processed, re-checked)
  3. Privacy     the test password must not appear anywhere in the KYC database or in n8n's execution data
  4. Decisions   approve a clean application; approving one that needs customer action is refused;
                 a second decision on the same application is refused

RESETS the KYC data. Writes results/<timestamp>.md; exits 1 when a quality gate fails.

    python evaluation/evaluate.py --url http://localhost:5678/webhook --intake-url http://localhost:8001 \
        --pg-container kyc-postgres --pg-user <user> --intake-container kyc-intake
Standard library only (Python 3.9+).
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import re
import subprocess
import sys
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DOCS = ROOT / "sample-documents"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read() or b"{}")


def psql(a, db, sql):
    return subprocess.run(["docker", "exec", "-i", a.pg_container, "psql", "-U", a.pg_user, "-d", db, "-tA", "-v", "ON_ERROR_STOP=1"],
                          input=sql.encode(), capture_output=True, check=True).stdout.decode("utf-8").strip()


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().upper()
    return " ".join(re.sub(r"[^A-Z0-9]", " ", s).split())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://localhost:5678/webhook")
    ap.add_argument("--intake-url", default="http://localhost:8001")
    ap.add_argument("--pg-container", default="kyc-postgres")
    ap.add_argument("--pg-user", default="postgres")
    ap.add_argument("--n8n-db", default="n8n", help="n8n's own database, searched for the test password")
    ap.add_argument("--intake-container", default="kyc-intake")
    ap.add_argument("--only", default="", help="comma-separated case ids")
    a = ap.parse_args()
    spec = json.loads((DOCS / "cases.json").read_text(encoding="utf-8"))
    cases = [c for c in spec["cases"] if not a.only or c["case"] in a.only.split(",")]
    gates, rows, field_rows = [], [], []

    print("0/4  offline tests…")
    unit = subprocess.run(["docker", "exec", a.intake_container, "python", "-m", "pytest", "-q", "tests"], capture_output=True)
    gates.append(("Intake service unit tests (MRZ, intake, validation)", unit.returncode == 0, (unit.stdout.decode().strip().splitlines() or ["no output"])[-1]))
    guard_file = HERE / "test-check-extractions.js"
    if guard_file.exists():
        try:
            g = subprocess.run(["node", str(guard_file)], capture_output=True)
            gates.append(("Extraction guardrail tests (real Claude responses)", g.returncode == 0, g.stdout.decode().strip().splitlines()[-1]))
        except FileNotFoundError:
            pass

    print("1/4  submitting the specimen applications…")
    psql(a, "kyc", "TRUNCATE kyc.applications, kyc.audit_log RESTART IDENTITY CASCADE;")
    results, total_cost, ai_calls = {}, 0.0, 0
    for c in cases:
        docs = [{"filename": f["file"], "declared_type": f["declared_type"],
                 "data_b64": base64.b64encode((DOCS / c["case"] / f["file"]).read_bytes()).decode()} for f in c["files"]]
        r = post(f"{a.url}/kyc/submit", {"reference": f"EVAL-{c['case']}", "applicant": c["applicant"], "documents": docs})
        results[c["case"]] = r
        total_cost += r.get("cost_usd", 0) or 0
        ai_calls += r.get("ai_calls", 0) or 0
        e = c["expect"]
        doc_status = {i["filename"]: i["status"] for i in r.get("intake", [])}
        fails = {x["code"] for x in r.get("checks", []) if x["result"] == "fail"}
        warns = {x["code"] for x in r.get("checks", []) if x["result"] == "warn"}
        ok = {
            "intake": all(doc_status.get(k) == v for k, v in e["doc_status"].items()),
            "status": r.get("status") == e["status"],
            "fails": set(e["fail"]) <= fails and (bool(e["fail"]) or not fails),
            "warns": set(e.get("warn", [])) <= warns,
            "ai": "ai_calls" not in e or r.get("ai_calls") == e["ai_calls"],
        }
        rows.append({"case": c["case"], "title": c["title"], **ok, "got_status": r.get("status"), "got_fails": sorted(fails),
                     "expected_fails": e["fail"], "ai_calls": r.get("ai_calls"), "cost": r.get("cost_usd")})
        print(f"     {c['case']}: {r.get('status')} · fails {sorted(fails)} · {r.get('ai_calls')} AI call(s) · ${r.get('cost_usd', 0):.4f}")

    print("2/4  password flow (C07)…")
    pw_case = next((c for c in cases if c["case"] == "C07"), None)
    pw_ok = True
    pw_detail = "skipped"
    password = None
    if pw_case:
        pw_file = next(f for f in pw_case["files"] if f.get("password"))
        password = pw_file["password"]
        doc_id = int(psql(a, "kyc", f"SELECT d.document_id FROM kyc.documents d JOIN kyc.applications ap USING (application_id) WHERE ap.reference = 'EVAL-C07' AND d.filename = '{pw_file['file']}'"))
        wrong = post(f"{a.intake_url}/unlock", {"document_id": doc_id, "password": "wrong-guess", "actor": "Evaluation"})
        right = post(f"{a.intake_url}/unlock", {"document_id": doc_id, "password": password, "actor": "Evaluation"})
        processed = right.get("processing") or {}
        exp = pw_case["expect"]["after_unlock"]
        pfails = {x["code"] for x in processed.get("checks", []) if x["result"] == "fail"}
        pw_ok = (wrong.get("ok") is False and wrong.get("attempts") == 1 and right.get("ok") is True
                 and processed.get("status") == exp["status"] and set(exp["fail"]) == pfails)
        pw_detail = f"wrong: refused (attempt {wrong.get('attempts')}); right: {right.get('status')} → application {processed.get('status')}, fails {sorted(pfails)}"
        total_cost += processed.get("cost_usd", 0) or 0
        ai_calls += processed.get("ai_calls", 0) or 0
        results["C07"] = processed or results["C07"]

    print("3/4  privacy and field accuracy…")
    leaks_kyc = int(psql(a, "kyc", f"""SELECT (SELECT count(*) FROM kyc.audit_log WHERE detail::text LIKE '%{password}%')
        + (SELECT count(*) FROM kyc.documents WHERE coalesce(status_reason,'') LIKE '%{password}%' OR coalesce(digital_text,'') LIKE '%{password}%')
        + (SELECT count(*) FROM kyc.extractions WHERE fields::text LIKE '%{password}%' OR coalesce(notes,'') LIKE '%{password}%')""")) if password else 0
    leaks_n8n = int(psql(a, a.n8n_db, f"SELECT count(*) FROM execution_data WHERE data LIKE '%{password}%'")) if password else 0
    supplied = int(psql(a, "kyc", "SELECT count(*) FROM kyc.audit_log WHERE event = 'password_supplied'")) if password else 0
    extracted = json.loads(psql(a, "kyc", """SELECT coalesce(json_agg(json_build_object('ref', ap.reference, 'file', d.filename, 'doc_type', e.doc_type, 'fields', e.fields)), '[]')
        FROM kyc.extractions e JOIN kyc.documents d USING (document_id) JOIN kyc.applications ap USING (application_id)"""))
    by_file = {(x["ref"], x["file"]): x for x in extracted}
    fields_total = fields_ok = types_total = types_ok = 0
    for c in cases:
        for f in c["files"]:
            truth = f.get("truth")
            got = by_file.get((f"EVAL-{c['case']}", f["file"]))
            if not truth or not got:
                continue
            types_total += 1
            types_ok += got["doc_type"] == truth["doc_type"]
            for k, v in truth.items():
                if k == "doc_type":
                    continue
                value = ((got["fields"] or {}).get(k) or {}).get("value")
                ok = norm(value) == norm(v)
                fields_total += 1
                fields_ok += ok
                if not ok:
                    field_rows.append(f"{c['case']} {f['file']} {k}: read {value!r}, true {v!r}")

    print("4/4  decisions…")
    app_of = lambda case: int(psql(a, "kyc", f"SELECT application_id FROM kyc.applications WHERE reference = 'EVAL-{case}'"))
    d1 = post(f"{a.url}/kyc/decide", {"application_id": app_of("C01"), "decision": "approve", "reviewer": "Evaluation"})
    d2 = post(f"{a.url}/kyc/decide", {"application_id": app_of("C04"), "decision": "approve", "reviewer": "Evaluation"})
    d3 = post(f"{a.url}/kyc/decide", {"application_id": app_of("C01"), "decision": "reject", "reviewer": "Evaluation"})

    n = len(rows)
    gates += [
        ("Intake status of every file", all(r["intake"] for r in rows), f"{sum(r['intake'] for r in rows)}/{n} applications"),
        ("Application status", all(r["status"] for r in rows), f"{sum(r['status'] for r in rows)}/{n}"),
        ("Expected failed checks raised (and none on clean applications)", all(r["fails"] for r in rows), f"{sum(r['fails'] for r in rows)}/{n}"),
        ("Expected warnings raised", all(r["warns"] for r in rows), f"{sum(r['warns'] for r in rows)}/{n}"),
        ("No AI call for files stopped at intake", all(r["ai"] for r in rows), f"{sum(r['ai'] for r in rows)}/{n}"),
        ("Document type read correctly", types_total and types_ok == types_total, f"{types_ok}/{types_total}"),
        ("Fields read exactly (name, birth date, number, expiry, bill date)", fields_total and fields_ok / fields_total >= 0.95, f"{fields_ok}/{fields_total}"),
        ("Password flow: wrong refused and counted, right opens and re-checks", pw_ok, pw_detail),
        ("Password never stored: KYC database", leaks_kyc == 0 and supplied >= 1, f"{leaks_kyc} occurrences; {supplied} 'password_supplied' audit event(s)"),
        ("Password never in n8n execution data", leaks_n8n == 0, f"{leaks_n8n} occurrences"),
        ("Approve a clean application", d1.get("ok") is True, d1.get("error") or "approved"),
        ("Approving an application that needs customer action is refused", d2.get("ok") is False, d2.get("error") or "accepted"),
        ("A second decision is refused", d3.get("ok") is False, d3.get("error") or "accepted"),
        ("AI cost for all applications", total_cost <= 1.0, f"${total_cost:.4f} for {ai_calls} document(s), ${total_cost / max(1, n):.4f} per application"),
    ]

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = HERE / "results"; out.mkdir(exist_ok=True)
    md = [f"# Evaluation {stamp}", "", "| Gate | Result | Value |", "|---|---|---|"] + [f"| {g} | {'PASS' if ok else 'FAIL'} | {v} |" for g, ok, v in gates]
    md += ["", "| Case | Application | Status | Failed checks (expected) | AI calls | Cost |", "|---|---|---|---|---|---|"]
    md += [f"| {r['case']} | {r['title']} | {r['got_status']} | {', '.join(r['got_fails']) or '-'} ({', '.join(r['expected_fails']) or 'none'}) | {r['ai_calls']} | ${r['cost'] or 0:.4f} |" for r in rows]
    if field_rows:
        md += ["", "## Fields read differently from the answer key", *[f"- {x}" for x in field_rows]]
    (out / f"{stamp}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print()
    for g, ok, v in gates:
        print(f"  {'PASS' if ok else 'FAIL'}  {g}: {v}")
    for x in field_rows:
        print(f"        field: {x}")
    print(f"\nReport: {out / (stamp + '.md')}")
    return 0 if all(ok for _, ok, _ in gates) else 1


if __name__ == "__main__":
    sys.exit(main())
