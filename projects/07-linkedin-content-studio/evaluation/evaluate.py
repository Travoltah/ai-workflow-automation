"""Live evaluation of the LinkedIn Content Studio against the website, n8n and the mock LinkedIn API.

A person approves twice in a real run, and so does this evaluation. The script never approves anything:

  python evaluation/evaluate.py draft      requests one article and one post, runs n8n, checks the drafts (gates 1-9)
      -> approve both drafts in /admin/studio
  python evaluation/evaluate.py publish    runs n8n, checks posting, comments, likes and reply drafts (gates 10-16)
      -> approve the genuine replies in /admin/studio/comments (skip the spam)
  python evaluation/evaluate.py replies    runs n8n, checks the replies were posted once, in the right threads (gates 17-19)

Settings come from the environment: STUDIO_API_TOKEN (required), SITE_URL (http://localhost:3000),
N8N_RUN_URL (http://localhost:5679/webhook/studio/run), MOCK_URL (http://localhost:8010).
Costs about $0.25 in Claude calls (one article, one post, six reply drafts). Standard library only.
"""

import json
import os
import re
import struct
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SITE = os.environ.get("SITE_URL", "http://localhost:3000").rstrip("/")
RUN = os.environ.get("N8N_RUN_URL", "http://localhost:5679/webhook/studio/run")
MOCK = os.environ.get("MOCK_URL", "http://localhost:8010").rstrip("/")
TOKEN = os.environ.get("STUDIO_API_TOKEN", "")
STATE = Path(__file__).with_name(".last-run.json")
BUDGET = {"article": 0.50, "post": 0.20, "run": 1.00}

REQUESTS = [
    {"format": "ARTICLE", "topic": "Test data is a data governance problem",
     "brief": "Teams copy production data into test environments because it is quick. That creates privacy risk and also bad tests, because real data "
              "rarely covers edge cases. Argue that test data needs owners, rules and quality checks just like production data. Draw on my QA and "
              "test automation work in fintech, kept general.",
     "keywords": ["test data", "governance"]},
    {"format": "POST", "topic": "Why AI test results need a human sign-off",
     "brief": "Short post: automated AI evaluations are useful but a person should own the go/no-go decision. Mention that in my own AI workflow "
              "projects the AI drafts and a human approves.",
     "keywords": ["sign", "human"]},
]
# A second, independent list (the website has its own): the phrases that most often give AI writing away.
AI_TELLS = ["delve", "tapestry", "game-changer", "game changer", "in today's fast-paced", "ever-evolving", "unlock the", "unleash",
            "it's important to note", "in conclusion", "let's dive in", "moreover", "furthermore", "paradigm shift", "synergy", "embark", "realm"]

results = []


def gate(n, name, ok, detail=""):
    results.append(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {n:>2}. {name}{'' if ok or not detail else f'  ({detail})'}")


def call(method, url, body=None, auth=True, raw=False):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if auth:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
            return r.status, (data if raw else json.loads(data or b"null"))
    except urllib.error.HTTPError as e:
        return e.code, None


def item(i):
    return call("GET", f"{SITE}/api/studio/items/{i}")[1]


def run_n8n(times=1, pause=25):
    for _ in range(times):
        call("POST", RUN, {}, auth=False)
        time.sleep(pause)


def png_size(data):
    return struct.unpack(">II", data[16:24]) if data[:8] == b"\x89PNG\r\n\x1a\n" else None


def article_structure(body):
    paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    heads = re.findall(r"^##\s+(.+)$", body, re.M)
    words = len(re.findall(r"[\w'’]+", re.sub(r"[#>*_`\[\]()!-]", " ", body)))
    problems = []
    if not re.match(r"^\*[^*].*[^*]\*$", paras[0], re.S): problems.append("opening is not italic")
    if not 5 <= len(heads) <= 8: problems.append(f"{len(heads)} sections")
    if not heads or not heads[-1].lower().startswith("final thought"): problems.append("last section is not Final thought")
    if not (re.match(r"^\*[^*]", paras[-1]) and "?" in paras[-1]): problems.append("no italic closing question")
    if body.count("{{INFOGRAPHIC}}") != 1: problems.append("infographic marker")
    if not re.search(r"^>\s*\*\*", body, re.M): problems.append("no bold blockquote line")
    if not re.search(r"^(\s*[-*]\s|\s*\d+\.\s)", body, re.M): problems.append("no list")
    if not 550 <= words <= 1000: problems.append(f"{words} words")
    return problems


# ───────────────────────── phase 1: drafts ─────────────────────────
def phase_draft():
    print("Phase 1: drafts\n")
    call("POST", f"{MOCK}/_reset", {}, auth=False)
    ids = []
    for r in REQUESTS:
        status, res = call("POST", f"{SITE}/api/studio/requests", {k: r[k] for k in ("format", "topic", "brief")})
        if status != 201:
            sys.exit(f"Couldn't create a request ({status}). Is the website running and STUDIO_API_TOKEN set?")
        ids.append(res["id"])
    STATE.write_text(json.dumps({"items": ids}))
    call("POST", RUN, {}, auth=False)
    for _ in range(40):
        time.sleep(15)
        items = [item(i) for i in ids]
        if all(x["status"] not in ("REQUESTED", "GENERATING") for x in items):
            break
    a, p = items
    gate(1, "both drafts arrived for review", [a["status"], p["status"]] == ["DRAFT", "DRAFT"], f"{a['status']}, {p['status']} {a.get('error') or ''}")
    gate(2, "no problem blocks approval (website style check)", a["lint"]["ok"] and p["lint"]["ok"], json.dumps([x["lint"]["errors"] for x in items])[:300])
    text = "\n".join(filter(None, [a["title"], a["body"], a["linkedinText"], p["title"], p["linkedinText"]]))
    gate(3, "no long dashes anywhere", not re.search(r"[—–]", text), re.findall(r".{20}[—–].{20}", text)[:2])
    tells = [t for t in AI_TELLS if re.search(rf"(?<![\w-]){re.escape(t)}(?![\w-])", text, re.I)]
    gate(4, "none of the common AI phrases (independent list)", not tells, ", ".join(tells))
    problems = article_structure(a["body"] or "")
    gate(5, "the article follows the earlier articles' structure", not problems, "; ".join(problems))
    hashtags = lambda t: len(re.findall(r"(^|\s)#[A-Za-z]\w*", t))
    post_ok = ("{{LINK}}" in a["linkedinText"] and "{{LINK}}" not in p["linkedinText"] and all(3 <= hashtags(x["linkedinText"]) <= 5 for x in items)
               and all(len(x["linkedinText"]) <= 3000 and "**" not in x["linkedinText"] for x in items))
    gate(6, "LinkedIn posts: link marker, 3-5 hashtags, plain text, under 3,000 characters", post_ok)
    on_topic = all(any(k in (x["title"] + (x["body"] or "") + x["linkedinText"]).lower() for k in r["keywords"]) for x, r in zip(items, REQUESTS))
    gate(7, "each draft is about the requested topic", on_topic)
    sizes = []
    for x, kinds in ((a, ["cover", "infographic"]), (p, ["cover"])):
        for k in kinds:
            status, data = call("GET", f"{SITE}/api/studio/image/{x['id']}/{k}", raw=True)
            sizes.append(png_size(data) if status == 200 else status)
    gate(8, "images render at the right sizes", sizes == [(1920, 1080), (1600, 2000), (1920, 1080)], sizes)
    gate(9, f"cost: article under ${BUDGET['article']}, post under ${BUDGET['post']}", a["costUsd"] < BUDGET["article"] and p["costUsd"] < BUDGET["post"],
         f"${a['costUsd']:.3f} + ${p['costUsd']:.3f}")
    print(f"\n  Drafts cost ${a['costUsd'] + p['costUsd']:.3f}. Next: approve both in {SITE}/admin/studio, then run: evaluate.py publish")


# ───────────────────────── phase 2: posting, comments, likes ─────────────────────────
def phase_publish():
    print("Phase 2: posting, comments and likes\n")
    ids = json.loads(STATE.read_text())["items"]
    if any(item(i)["status"] not in ("APPROVED", "PUBLISHED") for i in ids):
        sys.exit("Approve both drafts in /admin/studio first.")
    run_n8n(5, pause=45)                                # post, read comments, draft replies, like
    a, p = [item(i) for i in ids]
    st = call("GET", f"{MOCK}/_state", auth=False)[1]
    gate(10, "both items are live on LinkedIn", a["status"] == p["status"] == "PUBLISHED" and a["linkedinUrn"] in st["posts"] and p["linkedinUrn"] in st["posts"])
    gate(11, "exactly one LinkedIn post per approved item", len(st["posts"]) == 2, f"{len(st['posts'])} posts")
    status, html = call("GET", f"{SITE}/writing/{a['slug']}", auth=False, raw=True)
    html = html.decode("utf-8", "ignore") if isinstance(html, bytes) else ""
    gate(12, "the article is live on the website with its infographic and LinkedIn link",
         status == 200 and "infographic" in html and (a["post"] or {}).get("externalUrl") == a["linkedinUrl"])
    art_post = st["posts"][a["linkedinUrn"]]
    gate(13, "the article post is a link card to the website, with hashtags as templates",
         art_post["content"].get("article", {}).get("source", "").endswith(f"/writing/{a['slug']}") and "{hashtag|\\#|" in art_post["commentary"])
    comments = a["comments"] + p["comments"]
    gate(14, "comments read once, the author's own comment ignored", len(comments) == 6 and len({c["commentUrn"] for c in comments}) == 6, f"{len(comments)} comments")
    spam = [c for c in comments if "10x" in c["text"]]
    real = [c for c in comments if "10x" not in c["text"]]
    gate(15, "spam gets no reply and no like; genuine comments get a reply draft and a like",
         len(spam) == 2 and len(real) == 4 and all(not c["reply"] and not c["likedAt"] for c in spam) and all(c["reply"] and c["likedAt"] for c in real),
         [(c["authorName"], bool(c["reply"]), bool(c["likedAt"])) for c in comments])
    replies = " ".join(c["reply"] or "" for c in real)
    tells = [t for t in AI_TELLS if t in replies.lower()]
    gate(16, "reply drafts: no long dashes, hashtags or AI phrases",
         bool(real) and not re.search(r"[—–]", replies) and not re.search(r"(^|\s)#[A-Za-z]", replies) and not tells and all((c["lint"] or {}).get("ok", True) for c in real))
    reacts = st["reactions"]
    print(f"\n  {len(reacts)} likes sent. Next: approve the genuine replies in {SITE}/admin/studio/comments (skip the spam), then run: evaluate.py replies")


# ───────────────────────── phase 3: replies ─────────────────────────
def phase_replies():
    print("Phase 3: replies\n")
    ids = json.loads(STATE.read_text())["items"]
    run_n8n(2)
    comments = [c for i in ids for c in item(i)["comments"]]
    approved = [c for c in comments if c["status"] in ("APPROVED", "SENT")]
    st = call("GET", f"{MOCK}/_state", auth=False)[1]
    posted = [c for c in st["comments"].values() if c.get("parentComment")]
    gate(17, "every approved reply was posted", approved and all(c["status"] == "SENT" and c["replyUrn"] for c in approved), [(c["authorName"], c["status"]) for c in approved])
    gate(18, "each reply was posted once, under the right comment",
         len(posted) == len(approved) and sorted(x["parentComment"] for x in posted) == sorted(c["commentUrn"] for c in approved))
    run_n8n(1)
    st2 = call("GET", f"{MOCK}/_state", auth=False)[1]
    gate(19, "another run posts nothing new (no duplicates)", len(st2["posts"]) == len(st["posts"]) and len(st2["reactions"]) == len(st["reactions"])
         and len([c for c in st2["comments"].values() if c.get("parentComment")]) == len(posted))
    total = sum(item(i)["costUsd"] for i in ids) + sum(c["costUsd"] for c in comments)
    gate(20, f"whole run under ${BUDGET['run']}", total < BUDGET["run"], f"${total:.3f}")
    print(f"\n  Total AI cost for the evaluation: ${total:.3f}")


if __name__ == "__main__":
    if not TOKEN:
        sys.exit("Set STUDIO_API_TOKEN (the same value as in the website's .env).")
    phase = sys.argv[1] if len(sys.argv) > 1 else ""
    {"draft": phase_draft, "publish": phase_publish, "replies": phase_replies}.get(phase, lambda: sys.exit(__doc__))()
    print(f"\n{sum(results)}/{len(results)} gates passed")
    sys.exit(0 if all(results) else 1)
