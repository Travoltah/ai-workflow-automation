"""Unit tests for the collector's deterministic parts (no network, no database).

    docker compose run --rm collector python -m pytest -q tests
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collector import clean_text, diff, fingerprint, list_items  # noqa: E402

PAGE = """<html><head><title>Site title</title></head><body>
<header><nav><a href="/">Home</a> Menu</nav></header>
<main><h1>Breach notification</h1><p>Last updated: 2 September 2026</p>
<p>Notify   within 72 hours.</p><ul><li>Inform people.</li></ul><div><p>Nested paragraph.</p></div></main>
<footer>Copyright</footer><script>var x = 1;</script></body></html>"""


def test_clean_text_keeps_main_content_only():
    title, text = clean_text(PAGE)
    assert title == "Breach notification"
    assert "Home" not in text and "Copyright" not in text and "var x" not in text
    assert text.splitlines() == ["Breach notification", "Last updated: 2 September 2026", "Notify within 72 hours.", "Inform people.", "Nested paragraph."]


def test_ignore_patterns_drop_volatile_lines():
    _, text = clean_text(PAGE, ["^Last updated:"])
    assert "Last updated" not in text
    # so a page whose only change is that line has the same fingerprint
    _, other = clean_text(PAGE.replace("2 September", "14 November"), ["^Last updated:"])
    assert fingerprint(text) == fingerprint(other)


def test_fingerprint_ignores_whitespace_only():
    assert fingerprint("a  b\nc") == fingerprint("a b c")
    assert fingerprint("72 hours") != fingerprint("48 hours")


def test_diff_returns_only_changed_passages():
    old = "Intro stays.\nNotify within 72 hours.\nInform people."
    new = "Intro stays.\nNotify within 48 hours.\nInform people.\nKeep a breach register."
    d = diff(old, new)
    assert "REMOVED:\nNotify within 72 hours." in d
    assert "ADDED:\nNotify within 48 hours." in d and "Keep a breach register." in d
    assert "Intro stays." not in d and "Inform people." not in d


def test_list_items_rss():
    rss = """<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>
    <item><title>New guidance</title><link>http://x/a.html</link><pubDate>Sat, 14 Nov 2026 09:00:00 GMT</pubDate><description>&lt;p&gt;Summary&lt;/p&gt;</description></item>
    <item><title>Dup</title><link>http://x/a.html</link></item></channel></rss>"""
    items = list_items("rss", "http://x/feed.xml", rss, {})
    assert items == [{"url": "http://x/a.html", "title": "New guidance", "date": "2026-11-14", "summary": "Summary"}]


def test_list_items_json_api_mapping():
    body = json.dumps({"results": [{"html_url": "http://x/1", "title": "Rule", "publication_date": "2026-11-13", "abstract": "A"}]})
    cfg = {"list": "results", "url": "html_url", "title": "title", "date": "publication_date", "text": "abstract"}
    assert list_items("json_api", "http://x/api", body, cfg) == [{"url": "http://x/1", "title": "Rule", "date": "2026-11-13", "summary": "A"}]


def test_list_items_html_index_resolves_relative_links_and_caps():
    links = "".join(f'<a class="doc" href="docs/{i}.html">Doc {i}</a><a href="/about">About</a>' for i in range(30))
    items = list_items("html_index", "http://x/zw/notices/index.html", f"<main>{links}</main>", {"link_selector": "a.doc", "max_items": 5})
    assert len(items) == 5
    assert items[0] == {"url": "http://x/zw/notices/docs/0.html", "title": "Doc 0", "date": None, "summary": ""}


def test_list_items_html_page_is_one_item():
    assert list_items("html_page", "http://x/p.html", PAGE, {}) == [{"url": "http://x/p.html", "title": "", "date": None, "summary": ""}]
