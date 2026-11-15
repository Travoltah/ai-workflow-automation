"""A small stand-in for Jira Cloud, for demos and tests without a Jira site.

It implements only the calls this workflow makes:
    POST /rest/api/2/issue                 create a story or QA ticket
    GET  /rest/api/2/issue/{key}           read a story (with its links)
    POST /rest/api/3/search/jql            find stories by project + label
    POST /rest/api/2/issueLink             link a QA ticket to its story
    POST /rest/api/2/issue/{key}/comment   add a comment
    GET  /browse/{key}                     a plain page showing the issue (so links in the Excel work)
    GET  /_state                           everything stored, as JSON (for checks)

It starts with two stories in project CPAY: CPAY-1 has acceptance criteria, CPAY-2 has none.
Data lives in memory only. Any user name and token are accepted.

    python scripts/mock_jira.py --port 8089
Then set "jiraBaseUrl" in the Settings node to the address n8n can reach, for example
http://host.docker.internal:8089, and create a Jira credential with any e-mail and token.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOCK = threading.Lock()
ISSUES: dict[str, dict] = {}
LINKS: list[dict] = []
COMMENTS: dict[str, list] = {}
COUNTERS: dict[str, int] = {}
ISSUE_TYPES = {"Story", "Task", "Sub-task", "Subtask", "Bug", "Epic", "Test"}
LINK_TYPES = {"Relates": ("relates to", "relates to"), "Test": ("is tested by", "tests"), "Blocks": ("is blocked by", "blocks")}


def seed():
    add_issue({"project": {"key": "CPAY"}, "issuetype": {"name": "Story"},
               "summary": "Lock the account after repeated failed sign-in attempts",
               "description": "As a customer I want my account locked after repeated failed sign-ins so that nobody can "
                              "guess my password.\n\nh3. Acceptance criteria\n"
                              "# After 5 failed sign-in attempts within 15 minutes the account is locked for 30 minutes.\n"
                              "# The customer sees \"Your account is locked. Try again in 30 minutes or reset your password.\"\n"
                              "# A successful sign-in resets the failed-attempt counter.",
               "labels": ["security"], "components": [{"name": "Sign-in"}]})
    add_issue({"project": {"key": "CPAY"}, "issuetype": {"name": "Story"},
               "summary": "Show the last sign-in date on the dashboard",
               "description": "The dashboard shows when the customer last signed in, in the customer's time zone, "
                              "formatted like 14 Nov 2026, 09:41. First-time customers see \"Welcome! This is your first sign-in.\"",
               "labels": [], "components": [{"name": "Dashboard"}]})


def add_issue(fields: dict) -> dict:
    project = fields["project"]["key"]
    COUNTERS[project] = COUNTERS.get(project, 0) + 1
    key = f"{project}-{COUNTERS[project]}"
    issue = {"id": str(10000 + len(ISSUES)), "key": key, "fields": {
        "summary": fields.get("summary", ""), "description": fields.get("description", ""),
        "issuetype": {"name": fields["issuetype"]["name"]}, "status": {"name": "To Do"}, "priority": {"name": "Medium"},
        "labels": fields.get("labels", []), "components": fields.get("components", []),
        "parent": fields.get("parent")}}
    ISSUES[key] = issue
    return issue


def summary_of(key: str) -> dict:
    f = ISSUES[key]["fields"]
    return {"key": key, "fields": {"summary": f["summary"], "status": f["status"], "issuetype": f["issuetype"]}}


def with_links(issue: dict) -> dict:
    key = issue["key"]
    links = []
    for link in LINKS:
        inward, outward = LINK_TYPES.get(link["type"], (link["type"], link["type"]))
        kind = {"name": link["type"], "inward": inward, "outward": outward}
        if link["outward"] == key:
            links.append({"type": kind, "inwardIssue": summary_of(link["inward"])})
        elif link["inward"] == key:
            links.append({"type": kind, "outwardIssue": summary_of(link["outward"])})
    return {**issue, "fields": {**issue["fields"], "issuelinks": links}}


def search(jql: str) -> list[dict]:
    project = re.search(r'project\s*=\s*"?([A-Z0-9_]+)"?', jql)
    label = re.search(r'labels\s*=\s*"?([^"\s]+)"?', jql)
    found = [i for i in ISSUES.values()
             if (not project or i["key"].startswith(project.group(1) + "-"))
             and (not label or label.group(1) in i["fields"]["labels"])]
    return [with_links(i) for i in found]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"{self.command} {self.path} -> {args[1] if len(args) > 1 else ''}", flush=True)

    def send(self, status: int, body=None, content_type="application/json"):
        data = b"" if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}")

    def authorised(self) -> bool:
        if self.path.startswith(("/browse/", "/_state")) or (self.headers.get("Authorization") or "").startswith("Basic "):
            return True
        self.send(401, {"errorMessages": ["You are not authenticated. Authentication required to perform this operation."]})
        return False

    def do_GET(self):
        if not self.authorised():
            return
        path = self.path.split("?")[0]
        with LOCK:
            if path == "/_state":
                return self.send(200, {"issues": [with_links(i) for i in ISSUES.values()], "links": LINKS, "comments": COMMENTS})
            m = re.fullmatch(r"/rest/api/2/issue/([A-Z0-9_]+-\d+)", path)
            if m:
                issue = ISSUES.get(m.group(1))
                if not issue:
                    return self.send(404, {"errorMessages": ["Issue does not exist or you do not have permission to see it."], "errors": {}})
                return self.send(200, with_links(issue))
            m = re.fullmatch(r"/browse/([A-Z0-9_]+-\d+)", path)
            if m and m.group(1) in ISSUES:
                i = with_links(ISSUES[m.group(1)])
                page = (f"<h1>{i['key']}: {html.escape(i['fields']['summary'])}</h1><p><i>Mock Jira</i></p>"
                        f"<pre>{html.escape(i['fields']['description'])}</pre>"
                        f"<h3>Links</h3><pre>{html.escape(json.dumps(i['fields']['issuelinks'], indent=1))}</pre>"
                        f"<h3>Comments</h3><pre>{html.escape(json.dumps(COMMENTS.get(i['key'], []), indent=1))}</pre>")
                return self.send(200, page.encode(), "text/html; charset=utf-8")
        self.send(404, {"errorMessages": ["Not found"]})

    def do_POST(self):
        if not self.authorised():
            return
        path = self.path.split("?")[0]
        payload = self.body()
        with LOCK:
            if path == "/rest/api/2/issue":
                fields = payload.get("fields", {})
                errors = {}
                if not fields.get("summary"):
                    errors["summary"] = "You must specify a summary of the issue."
                if fields.get("issuetype", {}).get("name") not in ISSUE_TYPES:
                    errors["issuetype"] = "Specify a valid issue type"
                if not re.fullmatch(r"[A-Z][A-Z0-9_]+", fields.get("project", {}).get("key", "")):
                    errors["project"] = "Specify a valid project ID or key"
                if errors:
                    return self.send(400, {"errorMessages": [], "errors": errors})
                issue = add_issue(fields)
                host = self.headers.get("Host", "localhost")
                return self.send(201, {"id": issue["id"], "key": issue["key"], "self": f"http://{host}/rest/api/2/issue/{issue['id']}"})
            if path == "/rest/api/3/search/jql":
                found = search(payload.get("jql", ""))
                wanted = payload.get("fields") or ["summary"]
                issues = [{"id": i["id"], "key": i["key"], "fields": {k: i["fields"].get(k) for k in wanted}} for i in found]
                return self.send(200, {"issues": issues, "isLast": True})
            if path == "/rest/api/2/issueLink":
                inward = payload.get("inwardIssue", {}).get("key")
                outward = payload.get("outwardIssue", {}).get("key")
                kind = payload.get("type", {}).get("name")
                if inward not in ISSUES or outward not in ISSUES:
                    return self.send(404, {"errorMessages": ["Issue does not exist or you do not have permission to see it."]})
                if kind not in LINK_TYPES:
                    return self.send(404, {"errorMessages": [f"No issue link type with name '{kind}' found."]})
                LINKS.append({"type": kind, "inward": inward, "outward": outward})
                return self.send(201)
            m = re.fullmatch(r"/rest/api/2/issue/([A-Z0-9_]+-\d+)/comment", path)
            if m:
                if m.group(1) not in ISSUES:
                    return self.send(404, {"errorMessages": ["Issue does not exist or you do not have permission to see it."]})
                comment = {"id": str(len(sum(COMMENTS.values(), [])) + 1), "body": payload.get("body", "")}
                COMMENTS.setdefault(m.group(1), []).append(comment)
                return self.send(201, comment)
        self.send(404, {"errorMessages": ["Not found"]})


def main():
    parser = argparse.ArgumentParser(description="Mock Jira Cloud for the requirements-to-test-script workflow")
    parser.add_argument("--port", type=int, default=8089)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()
    seed()
    print(f"Mock Jira on http://{args.host}:{args.port}  (seeded CPAY-1, CPAY-2)", flush=True)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
