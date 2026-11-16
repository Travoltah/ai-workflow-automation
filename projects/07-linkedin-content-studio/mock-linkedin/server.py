"""Mock LinkedIn API for testing the Content Studio without touching a real account.

Implements the calls the workflow makes, and checks them the way LinkedIn does:
  GET  /v2/userinfo                                   who the token belongs to
  POST /rest/images?action=initializeUpload           returns an upload URL and an image URN
  PUT  /upload/<n>                                    the image bytes (must be a PNG or JPEG)
  POST /rest/posts                                    creates a post; 201 + x-restli-id
  GET  /rest/socialActions/<post urn>/comments        comments on a post
  POST /rest/socialActions/<comment urn>/comments     a reply (nested comment)
  POST /rest/reactions?actor=<urn>                    a like; 409 if already liked
Every /rest call needs the LinkedIn-Version and X-Restli-Protocol-Version: 2.0.0 headers and a bearer token.
A new post gets four comments: two genuine, one spam, and one by the author (which the workflow must skip).

Test helpers: GET /_log (every request), GET /_state, POST /_reset.  Standard library only.
"""

import json
import os
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlparse

PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://localhost:8010").rstrip("/")
ME = "urn:li:person:mockAuthor01"
RESERVED = set("|{}@[]()<>#\\*_~")


def fresh_state():
    # IDs keep growing across resets (like real URNs, they are never reused)
    return {"n": int(time.time() * 10) % 10**9 * 100, "images": {}, "posts": {}, "comments": {}, "reactions": set(), "log": []}


S = fresh_state()

SEED_COMMENTS = [
    ("urn:li:person:p1", "Rudo", "Moyo", "We hit exactly this last quarter. The model looked fine in testing, then a source system changed a date format and nobody noticed for three weeks. How do you get business teams to own the data checks instead of IT?"),
    ("urn:li:person:p2", "Daniel", "Okafor", "Useful framing. I'd add that lineage is usually the first thing to go when teams are under delivery pressure."),
    ("urn:li:person:p3", "Growth", "Hacks", "Great post!! I help professionals get 10x more followers in 30 days. DM me 'GROW' for my free guide."),
    (ME, "Mock", "Author", "Thanks all for reading. I'll reply to comments today."),
]


def unescaped_reserved(text):
    """Returns the first reserved character not escaped with a backslash (hashtag templates are allowed)."""
    stripped = re.sub(r"\{hashtag\|\\#\|[A-Za-z0-9_]+\}", "", text)
    i = 0
    while i < len(stripped):
        ch = stripped[i]
        if ch == "\\" and i + 1 < len(stripped):
            i += 2
            continue
        if ch in RESERVED:
            return ch
        i += 1
    return None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, status, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else b""
        self.send_response(status)
        if body is not None:
            self.send_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        S["log"].append({"at": time.time(), "method": self.command, "path": self.path, "status": status, "note": (body or {}).get("message", "") if isinstance(body, dict) else ""})

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _json(self):
        try:
            return json.loads(self._body() or b"{}")
        except json.JSONDecodeError:
            return None

    def _rest_ok(self):
        if not (self.headers.get("Authorization") or "").startswith("Bearer "):
            self._send(401, {"message": "Missing bearer token", "status": 401})
            return False
        if not re.fullmatch(r"\d{6}", self.headers.get("LinkedIn-Version") or ""):
            self._send(426, {"message": "LinkedIn-Version header (YYYYMM) is required", "status": 426})
            return False
        if self.headers.get("X-Restli-Protocol-Version") != "2.0.0":
            self._send(400, {"message": "X-Restli-Protocol-Version: 2.0.0 is required", "status": 400})
            return False
        return True

    # ───────────── GET ─────────────
    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/_log":
            return self._send(200, S["log"])
        if u.path == "/_state":
            return self._send(200, {
                "posts": S["posts"],
                "comments": S["comments"],
                "reactions": sorted(S["reactions"]),
                "images": {k: {kk: vv for kk, vv in v.items() if kk != "bytes"} for k, v in S["images"].items()},
            })
        if u.path == "/v2/userinfo":
            if not (self.headers.get("Authorization") or "").startswith("Bearer "):
                return self._send(401, {"message": "Missing bearer token"})
            return self._send(200, {"sub": ME.rsplit(":", 1)[1], "name": "Mock Author", "given_name": "Mock", "family_name": "Author"})
        m = re.fullmatch(r"/rest/socialActions/([^/]+)/comments", u.path)
        if m:
            if not self._rest_ok():
                return
            target = unquote(m.group(1))
            els = [c for c in S["comments"].values() if c["object"] == target]
            return self._send(200, {"elements": els, "paging": {"count": len(els), "start": 0}})
        self._send(404, {"message": f"No route {u.path}"})

    # ───────────── PUT (image bytes) ─────────────
    def do_PUT(self):
        m = re.fullmatch(r"/upload/(\d+)", urlparse(self.path).path)
        if not m:
            return self._send(404, {"message": "No such upload"})
        if not (self.headers.get("Authorization") or "").startswith("Bearer "):
            return self._send(401, {"message": "Missing bearer token"})
        data = self._body()
        img = next((v for v in S["images"].values() if v["upload"] == m.group(1)), None)
        if not img:
            return self._send(404, {"message": "Unknown upload"})
        if not (data.startswith(b"\x89PNG") or data.startswith(b"\xff\xd8")):
            return self._send(400, {"message": "Not a PNG or JPEG"})
        img.update(uploaded=True, size=len(data))
        self._send(201)

    # ───────────── POST ─────────────
    def do_POST(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/_reset":
            S.clear()
            S.update(fresh_state())
            return self._send(200, {"ok": True})
        if not self._rest_ok():
            return
        body = self._json()
        if body is None:
            return self._send(400, {"message": "Body is not JSON"})

        if u.path == "/rest/images" and q.get("action") == ["initializeUpload"]:
            owner = (body.get("initializeUploadRequest") or {}).get("owner")
            if owner != ME:
                return self._send(403, {"message": f"Owner must be the token's member ({ME})"})
            S["n"] += 1
            urn = f"urn:li:image:D{S['n']:04d}"
            S["images"][urn] = {"upload": str(S["n"]), "uploaded": False}
            return self._send(200, {"value": {"uploadUrlExpiresAt": int(time.time() * 1000) + 3600_000, "uploadUrl": f"{PUBLIC_URL}/upload/{S['n']}", "image": urn}})

        if u.path == "/rest/posts":
            problems = []
            if body.get("author") != ME:
                problems.append("author must be the token's member")
            text = body.get("commentary") or ""
            bad = unescaped_reserved(text)
            if not text.strip():
                problems.append("commentary is empty")
            if bad:
                problems.append(f"commentary has an unescaped reserved character '{bad}'")
            if len(text) > 3000:
                problems.append("commentary is over 3000 characters")
            if body.get("lifecycleState") != "PUBLISHED" or body.get("visibility") not in ("PUBLIC", "CONNECTIONS"):
                problems.append("lifecycleState/visibility missing")
            content = body.get("content") or {}
            image = (content.get("article") or {}).get("thumbnail") or (content.get("media") or {}).get("id")
            if not image or not S["images"].get(image, {}).get("uploaded"):
                problems.append("content image was not uploaded")
            if "article" in content and not str(content["article"].get("source", "")).startswith("http"):
                problems.append("article.source must be a URL")
            if problems:
                return self._send(422, {"message": "; ".join(problems), "status": 422})
            S["n"] += 1
            urn = f"urn:li:share:{7300000000000000000 + S['n']}"
            S["posts"][urn] = {"commentary": text, "content": content, "created": time.time()}
            for actor, first, last, msg in SEED_COMMENTS:
                S["n"] += 1
                cid = str(7300000000000000000 + S["n"])
                curn = f"urn:li:comment:({urn},{cid})"
                S["comments"][curn] = {
                    "id": cid, "commentUrn": curn, "object": urn, "actor": actor, "message": {"text": msg},
                    "created": {"time": int(time.time() * 1000)}, "actor~": {"localizedFirstName": first, "localizedLastName": last},
                }
            return self._send(201, None, {"x-restli-id": urn})

        m = re.fullmatch(r"/rest/socialActions/([^/]+)/comments", u.path)
        if m:
            parent = unquote(m.group(1))
            if parent not in S["comments"]:
                return self._send(404, {"message": f"No comment {parent}"})
            if body.get("actor") != ME:
                return self._send(403, {"message": "actor must be the token's member"})
            if body.get("parentComment") != parent:
                return self._send(400, {"message": "parentComment must match the comment in the URL"})
            if body.get("object") != S["comments"][parent]["object"]:
                return self._send(400, {"message": "object must be the post the comment is on"})
            text = ((body.get("message") or {}).get("text") or "").strip()
            if not text or len(text) > 1250:
                return self._send(400, {"message": "message.text must be 1-1250 characters"})
            S["n"] += 1
            cid = str(7300000000000000000 + S["n"])
            curn = f"urn:li:comment:({S['comments'][parent]['object']},{cid})"
            S["comments"][curn] = {"id": cid, "commentUrn": curn, "object": S["comments"][parent]["object"], "actor": ME, "parentComment": parent, "message": {"text": text}, "created": {"time": int(time.time() * 1000)}}
            return self._send(201, {"commentUrn": curn, "id": cid}, {"x-restli-id": quote(curn)})

        if u.path == "/rest/reactions":
            actor = (q.get("actor") or [""])[0]
            if actor != ME:
                return self._send(403, {"message": "actor must be the token's member"})
            root = body.get("root")
            if root not in S["comments"]:
                return self._send(404, {"message": f"No comment {root}"})
            if body.get("reactionType") != "LIKE":
                return self._send(400, {"message": "reactionType LIKE expected"})
            key = f"{actor}|{root}"
            if key in S["reactions"]:
                return self._send(409, {"message": "Already reacted"})
            S["reactions"].add(key)
            return self._send(201, {"root": root, "reactionType": "LIKE"})

        self._send(404, {"message": f"No route {u.path}"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print(f"mock LinkedIn on :{port} (public URL {PUBLIC_URL})", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
