"""Creates the sample Contoso Pay stories as issues in your Jira Cloud project.

The token is read from environment variables, never from arguments or files:

    PowerShell:
        $env:JIRA_BASE_URL  = "https://your-site.atlassian.net"
        $env:JIRA_EMAIL     = "you@example.com"
        $env:JIRA_API_TOKEN = "<token from id.atlassian.com/manage-profile/security/api-tokens>"
        python scripts/create_sample_jira_issues.py --project CPAY --count 5

    --label ai-test-gen   (default) lets the scheduled scan pick the stories up automatically.
    --label ""            creates them without the label.
    --dry-run             prints what would be created.

Standard library only (Python 3.9+).
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

STORIES = Path(__file__).resolve().parent.parent / "sample-stories" / "stories.json"


def adf(story: dict) -> dict:
    """Description in Atlassian Document Format, with an 'Acceptance criteria' heading and bullet list."""
    para = lambda text: {"type": "paragraph", "content": [{"type": "text", "text": text}]}
    return {
        "type": "doc", "version": 1,
        "content": [
            para(story["description"]),
            {"type": "heading", "attrs": {"level": 3}, "content": [{"type": "text", "text": "Acceptance criteria"}]},
            {"type": "bulletList", "content": [{"type": "listItem", "content": [para(ac)]} for ac in story["acceptanceCriteria"]]},
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", required=True, help="Jira project key, e.g. CPAY")
    parser.add_argument("--count", type=int, default=5, help="how many sample stories to create (max 16)")
    parser.add_argument("--issue-type", default="Story")
    parser.add_argument("--label", default="ai-test-gen")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    stories = json.loads(STORIES.read_text(encoding="utf-8"))[: args.count]
    if args.dry_run:
        for s in stories:
            print(f"would create: [{args.project}] {s['summary']} ({len(s['acceptanceCriteria'])} criteria)")
        return 0

    missing = [v for v in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN") if not os.environ.get(v)]
    if missing:
        print("Set these environment variables first: " + ", ".join(missing), file=sys.stderr)
        return 2
    base = os.environ["JIRA_BASE_URL"].rstrip("/")
    auth = base64.b64encode(f"{os.environ['JIRA_EMAIL']}:{os.environ['JIRA_API_TOKEN']}".encode()).decode()

    for s in stories:
        fields = {"project": {"key": args.project}, "issuetype": {"name": args.issue_type},
                  "summary": s["summary"], "description": adf(s)}
        if args.label:
            fields["labels"] = [args.label]
        request = urllib.request.Request(
            f"{base}/rest/api/3/issue", data=json.dumps({"fields": fields}).encode(), method="POST",
            headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                key = json.loads(response.read())["key"]
            print(f"created {key}: {s['summary']}")
        except urllib.error.HTTPError as error:
            print(f"failed: {s['summary']}: HTTP {error.code} {error.read().decode('utf-8', 'replace')[:300]}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
