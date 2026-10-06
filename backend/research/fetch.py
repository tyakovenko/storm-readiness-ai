"""Fetch a source page as text. Researcher and judge each own a Fetcher (separate caches): the judge
checks the page as it gets it, never the researcher's copy (ADR layered-judge).

Errors come back as Page.error, so a source that can't be read is reported as unchecked, never skipped.
PDFs return an error until extraction keeps layout and tables intact (issue #8).
"""

from __future__ import annotations

import html as _html
import json
import logging
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser

from research import policy
from research.schema import Page

log = logging.getLogger(__name__)

# Several county and FEMA hosts answer 403 to the default Python-urllib agent.
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) storm-readiness-research/0.1"
# Browser-like: some hosts answer 406 to a narrower Accept list (Harris run 2026-10-05).
ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.9,*/*;q=0.8"
TIMEOUT_S = 20        # per socket operation
TOTAL_TIMEOUT_S = 60  # per download: a server trickling bytes passes every per-read timeout
MAX_BYTES = 5_000_000
# Less text = JS-rendered shell or an error page; checking it would fail every quote. A JSON query with
# one record is legitimately short.
MIN_TEXT_CHARS = {"html": 200, "other": 40}
PDF_ERROR = "PDF not supported yet (issue #8)"

_BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "table",
          "ul", "ol", "header", "footer", "blockquote", "dt", "dd", "caption"}
_SKIP = {"script", "style", "noscript", "svg", "template", "head"}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self.skip += 1
        elif tag in _BLOCK:
            self.out.append("\n")
        elif tag in ("td", "th"):
            self.out.append(" | ")  # keep cells apart so "12" and "300" don't merge into "12300"

    def handle_endtag(self, tag):
        if tag in _SKIP and self.skip:
            self.skip -= 1
        elif tag in _BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


_LEAKED_TAG = re.compile(r"</?[a-zA-Z][a-zA-Z0-9]{0,10}(?:\s[^<>]{0,200})?/?>")


def html_to_text(html: str) -> str:
    p = _Text()
    p.feed(html)
    # Some CMSs embed escaped article HTML as text ("&lt;p&gt;...&amp;ldquo;"); after one decode it shows up
    # as literal "<p>" and "&ldquo;" (Texas Tribune). Strip and decode once more so quotes are clean text.
    text = _html.unescape(_LEAKED_TAG.sub(" ", "".join(p.out)))
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\s*\n\s*", "\n", text).strip()


def json_to_text(raw: str) -> str:
    """One line per record ("KEY: value; KEY: value"), so a record is one sentence for the quote and unit
    checks. ArcGIS feature JSON -> attributes per feature; other JSON -> "path: value" per scalar."""
    d = json.loads(raw)
    if isinstance(d, dict) and isinstance(d.get("features"), list):
        rows = [f.get("attributes") or f.get("properties") or {} for f in d["features"]]
        return "\n".join("; ".join(f"{k}: {v}" for k, v in r.items() if v not in (None, "")) for r in rows)
    lines: list[str] = []

    def walk(v, path):
        if isinstance(v, dict):
            for k, x in v.items():
                walk(x, f"{path}.{k}" if path else str(k))
        elif isinstance(v, list):
            for i, x in enumerate(v):
                walk(x, f"{path}[{i}]")
        elif v not in (None, ""):
            lines.append(f"{path}: {v}")
    walk(d, "")
    return "\n".join(lines)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _get(url: str) -> Page:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": ACCEPT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            final, ctype = r.geturl(), (r.headers.get_content_type() or "").lower()
            charset = r.headers.get_content_charset() or "utf-8"
            chunks, size, t0 = [], 0, time.monotonic()
            while size <= MAX_BYTES:
                if time.monotonic() - t0 > TOTAL_TIMEOUT_S:
                    return Page(url=url, error=f"download exceeded {TOTAL_TIMEOUT_S} s", retrieved=_now())
                chunk = r.read(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            body = b"".join(chunks)
    except urllib.error.HTTPError as e:
        return Page(url=url, error=f"HTTP {e.code}", retrieved=_now())
    except Exception as e:  # DNS, TLS, timeout: reported on the fact as unchecked
        return Page(url=url, error=f"{type(e).__name__}: {e}", retrieved=_now())
    page = Page(url=url, final_url=final, content_type=ctype, retrieved=_now())
    if ctype == "application/pdf" or body[:5] == b"%PDF-":
        return page.model_copy(update={"error": PDF_ERROR})
    if len(body) > MAX_BYTES:
        return page.model_copy(update={"error": f"larger than {MAX_BYTES} bytes"})
    raw = body.decode(charset, errors="replace")
    if ctype == "application/json" or raw.lstrip()[:1] in ("{", "["):  # ArcGIS often says text/plain
        try:
            text = json_to_text(raw)
        except ValueError as e:
            return page.model_copy(update={"error": f"invalid JSON: {e}"})
    elif ctype in ("text/html", "application/xhtml+xml"):
        text = html_to_text(raw)
    elif ctype.startswith("text/") or ctype == "application/xml":
        text = raw.strip()
    else:
        return page.model_copy(update={"error": f"unsupported content type {ctype or 'unknown'}"})
    min_chars = MIN_TEXT_CHARS["html" if ctype in ("text/html", "application/xhtml+xml") else "other"]
    if len(text) < min_chars:
        return page.model_copy(update={"text": text, "error": f"only {len(text)} chars of text (JS-rendered page?)"})
    return page.model_copy(update={"text": text})


class Fetcher:
    """One per role per run: caches by URL, enforces the run's fetch cap."""

    def __init__(self, max_fetches: int = policy.MAX_FETCHES, get=_get):
        self.max_fetches = max_fetches
        self._get = get
        self.cache: dict[str, Page] = {}
        self.count = 0

    def __call__(self, url: str) -> Page:
        if url in self.cache:
            return self.cache[url]
        if self.count >= self.max_fetches:
            return Page(url=url, error=f"fetch cap reached ({self.max_fetches} per run)", retrieved=_now())
        self.count += 1
        page = self._get(url)
        if page.error:
            log.warning("fetch %s: %s", url, page.error)
        self.cache[url] = page
        if page.final_url and page.final_url != url:
            self.cache.setdefault(page.final_url, page)
        return page
