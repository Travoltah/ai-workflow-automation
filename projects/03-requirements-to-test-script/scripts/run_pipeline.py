"""Runs the workflow through its API and saves the Excel test script.

    python scripts/run_pipeline.py --document "sample-input/CR-2026-014 Loan Settlement Logic V1.0.docx" \
        --wireframe sample-input/wireframe-settle-loan.png --wireframe sample-input/wireframe-settlement-failed.png

    python scripts/run_pipeline.py --jira-stories CPAY-1,CPAY-2 --create-jira

Options:
    --url            the workflow's API (default http://localhost:5678/webhook/req2test/run)
    --document       an FSD / Change Request (.docx, .pdf, .txt, .md); repeat for several
    --wireframe      an image or PDF; repeat for several
    --figma          a Figma link (needs FIGMA_TOKEN in .env)
    --jira-stories   existing Jira story keys, comma-separated (read, never recreated)
    --project        Jira project for new stories
    --create-jira    create stories and QA tickets in Jira (default: preview, Excel only)
    --out            where to save the .xlsx (default: the name the workflow gives it, in sample-output/)
Standard library only (Python 3.9+). Runs take a few minutes: one Claude call per story.
"""
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def encode(path: str) -> dict:
    p = Path(path)
    return {"name": p.name, "mimeType": mimetypes.guess_type(p.name)[0] or "", "data": base64.b64encode(p.read_bytes()).decode()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://localhost:5678/webhook/req2test/run")
    parser.add_argument("--document", action="append", default=[])
    parser.add_argument("--wireframe", action="append", default=[])
    parser.add_argument("--figma", default="")
    parser.add_argument("--jira-stories", default="")
    parser.add_argument("--project", default="")
    parser.add_argument("--create-jira", action="store_true")
    parser.add_argument("--system-name", default="")
    parser.add_argument("--prefix", default="")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    body = {
        "documents": [encode(p) for p in args.document],
        "wireframes": [encode(p) for p in args.wireframe],
        "figmaUrl": args.figma,
        "jiraStories": args.jira_stories,
        "jiraProjectKey": args.project,
        "createJiraTickets": args.create_jira,
        "systemName": args.system_name,
        "testIdPrefix": args.prefix,
    }
    request = urllib.request.Request(args.url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=1800) as response:
            content = response.read()
            disposition = response.headers.get("Content-Disposition") or ""
    except urllib.error.HTTPError as error:
        print(f"HTTP {error.code}: {error.read().decode('utf-8', 'replace')[:500]}", file=sys.stderr)
        print("Open the execution in n8n (Overview > Executions) to see which step failed.", file=sys.stderr)
        return 1
    if not content.startswith(b"PK"):
        print(f"Expected an .xlsx file but got: {content[:300]!r}", file=sys.stderr)
        return 1

    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', disposition)
    out = Path(args.out) if args.out else ROOT / "sample-output" / (urllib.request.unquote(match.group(1)) if match else "test-script.xlsx")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(content)
    print(f"Saved {out} ({len(content) // 1024} KB) in {time.time() - started:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
