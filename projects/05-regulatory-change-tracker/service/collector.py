"""Collector: reads a source, extracts clean text, detects new and amended documents, records source health.

Deterministic, no AI. For each source:
  1. list items       rss | json_api | html_index | html_page
  2. fetch and clean  main content only; lines matching the source's ignore_patterns are dropped
  3. compare          SHA-256 of the clean text against the stored version
  4. record           new document -> change 'new' (full text); different hash -> change 'amended'
                      (only the changed passages); the first check of a source is a baseline (no changes)
  5. health           ok | empty | error, with the error message, per source and run
"""
from __future__ import annotations

import datetime as dt
import difflib
import hashlib
import re
import time
from urllib.parse import urljoin

import feedparser
import httpx
from bs4 import BeautifulSoup

UA = "RegChangeTracker/1.0 (+https://github.com/Travoltah/ai-workflow-automation)"
MAX_ITEMS = 15            # per source per run; feeds list newest first
MAX_DIFF_CHARS = 15000    # what is sent to the model per change
MAX_TEXT_CHARS = 200000   # what is stored per document version
BLOCKS = ["h1", "h2", "h3", "h4", "p", "li", "td", "th", "pre", "blockquote", "dt", "dd"]


# ── text ─────────────────────────────────────────────────────────────────────
def clean_text(markup: str, ignore_patterns: list[str] | None = None) -> tuple[str, str]:
    """Returns (title, text): the main content as one block per line, without navigation, headers or footers."""
    soup = BeautifulSoup(markup, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript", "form", "aside", "svg"]):
        tag.decompose()
    root = soup.find("main") or soup.find("article") or soup.body or soup
    h1 = root.find("h1")
    title = " ".join((h1.get_text(" ", strip=True) if h1 else (soup.title.get_text(" ", strip=True) if soup.title else "")).split())
    lines = []
    for el in root.find_all(BLOCKS):
        if el.find(BLOCKS):                      # a container of other blocks: its children are read instead
            continue
        text = " ".join(el.get_text(" ", strip=True).split())
        if text:
            lines.append(text)
    if not lines:
        lines = [" ".join(l.split()) for l in root.get_text("\n").splitlines() if l.strip()]
    patterns = [re.compile(p, re.I) for p in (ignore_patterns or [])]
    lines = [l for l in lines if not any(p.search(l) for p in patterns)]
    return title, "\n".join(lines)[:MAX_TEXT_CHARS]


def fingerprint(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).encode()).hexdigest()


def diff(old: str, new: str) -> str:
    """Only the changed passages, paragraph by paragraph, labelled REMOVED / ADDED."""
    a, b = old.splitlines(), new.splitlines()
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag in ("replace", "delete"):
            out.append("REMOVED:\n" + "\n".join(a[i1:i2]))
        if tag in ("replace", "insert"):
            out.append("ADDED:\n" + "\n".join(b[j1:j2]))
    return "\n\n".join(out)[:MAX_DIFF_CHARS]


def to_date(value) -> str | None:
    if not value:
        return None
    if isinstance(value, time.struct_time):
        return dt.date(*value[:3]).isoformat()
    m = re.search(r"\d{4}-\d{2}-\d{2}", str(value))
    return m.group(0) if m else None


# ── listing ──────────────────────────────────────────────────────────────────
def list_items(method: str, url: str, body: str, cfg: dict) -> list[dict]:
    """[{url, title, date, summary}] from a feed, an API response or an index page. html_page is one item."""
    limit = int(cfg.get("max_items", MAX_ITEMS))
    if method == "rss":
        feed = feedparser.parse(body)
        items = [{"url": e.get("link"), "title": e.get("title", ""), "date": to_date(e.get("published_parsed") or e.get("updated_parsed") or e.get("published")),
                  "summary": clean_text(e.get("summary", ""))[1] if e.get("summary") else ""} for e in feed.entries]
    elif method == "json_api":
        import json
        data = json.loads(body)
        rows = data
        for key in str(cfg.get("list", "")).split("."):
            if key:
                rows = rows[key]
        items = [{"url": r.get(cfg.get("url", "url")), "title": r.get(cfg.get("title", "title"), ""),
                  "date": to_date(r.get(cfg.get("date", "date"))), "summary": r.get(cfg["text"], "") if cfg.get("text") else ""} for r in rows]
    elif method == "html_index":
        soup = BeautifulSoup(body, "html.parser")
        items = [{"url": urljoin(url, a.get("href")), "title": " ".join(a.get_text(" ", strip=True).split()), "date": None, "summary": ""}
                 for a in soup.select(cfg.get("link_selector", "a")) if a.get("href")]
    elif method == "html_page":
        return [{"url": url, "title": "", "date": None, "summary": ""}]
    else:
        raise ValueError(f"Unknown method {method}")
    seen, unique = set(), []
    for i in items:
        if i["url"] and i["url"] not in seen:
            seen.add(i["url"])
            unique.append(i)
    return unique[:limit]


# ── collecting ───────────────────────────────────────────────────────────────
def fetch(client: httpx.Client, url: str) -> str:
    r = client.get(url)
    r.raise_for_status()
    return r.text


def read_item(client, method: str, item: dict, cfg: dict, page_body: str | None) -> tuple[str, str]:
    """(title, text) for one item: the fetched page, or the feed's own title and summary."""
    ignore = cfg.get("ignore_patterns", [])
    if method == "html_page":
        return clean_text(page_body, ignore)
    if cfg.get("fetch_pages", method == "html_index"):
        title, text = clean_text(fetch(client, item["url"]), ignore)
        return title or item["title"], text
    return item["title"], "\n".join(x for x in (item["title"], item["summary"]) if x)


def collect(conn, source_id: int, run_id: int, client: httpx.Client | None = None) -> dict:
    """Checks one source for one run and records everything. Returns a summary for n8n."""
    t0 = time.time()
    own_client = client is None
    client = client or httpx.Client(headers={"User-Agent": UA}, timeout=30, follow_redirects=True)
    with conn.cursor() as cur:
        cur.execute("SELECT code, method, url, config FROM reg.sources WHERE source_id = %s", (source_id,))
        code, method, url, cfg = cur.fetchone()
        cur.execute("SELECT count(*) FROM reg.source_checks WHERE source_id = %s AND status IN ('baseline', 'ok', 'empty')", (source_id,))
        baseline = cur.fetchone()[0] == 0
    result = {"source_id": source_id, "code": code, "status": None, "items_seen": 0, "new_docs": 0, "amended_docs": 0,
              "item_errors": [], "error": None}
    try:
        body = fetch(client, url)
        items = list_items(method, url, body, cfg)
        result["items_seen"] = len(items)
        with conn.transaction():
            with conn.cursor() as cur:
                for item in items:
                    try:
                        title, text = read_item(client, method, item, cfg, body)
                    except Exception as e:                   # one broken item doesn't stop the source
                        result["item_errors"].append(f"{item['url']}: {e}"[:300])
                        continue
                    if not text.strip():
                        result["item_errors"].append(f"{item['url']}: no text extracted")
                        continue
                    h = fingerprint(text)
                    cur.execute("SELECT doc_id, version, current_hash, current_text FROM reg.documents WHERE source_id = %s AND url = %s",
                                (source_id, item["url"]))
                    row = cur.fetchone()
                    if row is None:
                        cur.execute("""INSERT INTO reg.documents (source_id, url, title, published_at, current_hash, current_text, first_seen_run, last_changed_run)
                                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING doc_id""",
                                    (source_id, item["url"], title or item["title"] or item["url"], item["date"], h, text, run_id, run_id))
                        doc_id = cur.fetchone()[0]
                        cur.execute("INSERT INTO reg.document_versions (doc_id, version, hash, text, run_id) VALUES (%s, 1, %s, %s, %s)", (doc_id, h, text, run_id))
                        if not baseline:
                            cur.execute("INSERT INTO reg.changes (run_id, doc_id, version, change_type, diff_text) VALUES (%s, %s, 1, 'new', %s)",
                                        (run_id, doc_id, text[:MAX_DIFF_CHARS]))
                            result["new_docs"] += 1
                    elif row[2] != h:
                        doc_id, version, _, old_text = row
                        cur.execute("""UPDATE reg.documents SET version = %s, current_hash = %s, current_text = %s, title = %s, last_changed_run = %s
                                       WHERE doc_id = %s""", (version + 1, h, text, title or item["title"] or item["url"], run_id, doc_id))
                        cur.execute("INSERT INTO reg.document_versions (doc_id, version, hash, text, run_id) VALUES (%s, %s, %s, %s, %s)",
                                    (doc_id, version + 1, h, text, run_id))
                        if not baseline:
                            cur.execute("INSERT INTO reg.changes (run_id, doc_id, version, change_type, diff_text) VALUES (%s, %s, %s, 'amended', %s)",
                                        (run_id, doc_id, version + 1, diff(old_text, text)))
                            result["amended_docs"] += 1
        result["status"] = "baseline" if baseline else ("empty" if not items else "ok")
    except Exception as e:
        result["status"] = "error"
        result["error"] = f"{type(e).__name__}: {e}"[:500]
    finally:
        if own_client:
            client.close()
    error = result["error"] or ("; ".join(result["item_errors"])[:500] if result["item_errors"] else None)
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO reg.source_checks (run_id, source_id, status, items_seen, new_docs, amended_docs, error, duration_ms)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                           ON CONFLICT (run_id, source_id) DO UPDATE SET status = EXCLUDED.status, items_seen = EXCLUDED.items_seen,
                             new_docs = EXCLUDED.new_docs, amended_docs = EXCLUDED.amended_docs, error = EXCLUDED.error, duration_ms = EXCLUDED.duration_ms""",
                        (run_id, source_id, result["status"], result["items_seen"], result["new_docs"], result["amended_docs"], error,
                         int((time.time() - t0) * 1000)))
            cur.execute("""UPDATE reg.sources SET last_checked_at = now(), last_status = %s, last_error = %s, last_item_count = %s WHERE source_id = %s""",
                        (result["status"], error, result["items_seen"], source_id))
    return result
