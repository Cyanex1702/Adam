"""Extractive web evidence and a small text browser. HTML never runs scripts."""

import hashlib
import json
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlencode, urljoin

from adam.core.privacy import contains_secret
from adam.internet.network import InternetError, Network, Response, safe_url


class Document(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title: list[str] = []
        self.links: list[dict[str, str]] = []
        self.forms: list[dict[str, Any]] = []
        self.hidden = 0
        self.in_title = False
        self.form: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag in {"script", "style", "template", "noscript", "svg"}:
            self.hidden += 1
        if self.hidden:
            return
        if tag == "title":
            self.in_title = True
        if tag == "a" and values.get("href") and len(self.links) < 100:
            self.links.append({"url": str(values["href"]), "label": ""})
        if tag == "form" and len(self.forms) < 20:
            self.form = {
                "action": values.get("action", ""),
                "method": str(values.get("method", "get")).upper(),
                "encoding": values.get("enctype", "application/x-www-form-urlencoded"),
                "fields": {},
            }
            self.forms.append(self.form)
        if tag == "input" and self.form and values.get("name"):
            kind = values.get("type", "text")
            if re.search(r"password|secret|token|api.?key", str(values["name"]), re.I):
                self.form["unsupported"] = True
                return
            if values["name"] in self.form["fields"]:
                self.form["unsupported"] = True
                return
            if kind in {"text", "search", "email", "number", "hidden"}:
                self.form["fields"][str(values["name"])] = {
                    "type": kind,
                    "value": str(values.get("value", ""))[:2048],
                }
            else:
                self.form["unsupported"] = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "template", "noscript", "svg"}:
            self.hidden = max(0, self.hidden - 1)
        if tag == "title":
            self.in_title = False
        if tag == "form":
            self.form = None

    def handle_data(self, value: str) -> None:
        if not self.hidden:
            self.parts.append(value.strip())
            if self.in_title:
                self.title.append(value)


def document(reply: Response) -> dict[str, Any]:
    if reply.status != 200:
        raise InternetError("INTERNET.HTTP_FAILED")
    content_type = reply.headers.get("content-type", "").split(";")[0].lower()
    if content_type not in {"text/html", "text/plain"}:
        raise InternetError("INTERNET.CONTENT_TYPE_DENIED")
    raw = reply.body.decode("utf-8", errors="replace")
    parser = Document()
    if content_type == "text/html":
        parser.feed(raw)
        text, title = " ".join(parser.parts), "".join(parser.title).strip()
    else:
        text, title = raw, reply.url
    if contains_secret(text) or contains_secret(json.dumps(parser.forms)):
        raise InternetError("INTERNET.SECRET_OUTPUT_DENIED")
    links = []
    for link in parser.links:
        try:
            links.append({"url": safe_url(urljoin(reply.url, link["url"]))})
        except InternetError:
            continue
    return {
        "url": reply.url,
        "title": title[:300],
        "text": text[:24000],
        "links": links,
        "forms": parser.forms,
        "source_kind": "WEB",
        "trust": "UNTRUSTED_DATA",
        "epistemic_status": "RETRIEVED",
        "fetched_at": reply.fetched_at,
        "last_modified": reply.headers.get("last-modified"),
        "freshness": "FETCHED_NOW; publication date and factual accuracy unverified",
        "sha256": hashlib.sha256(reply.body).hexdigest(),
    }


class Web:
    def __init__(self, network: Network) -> None:
        self.network = network

    def fetch(self, url: str) -> dict[str, Any]:
        return document(self.network.request(url))

    def search(self, query: str, provider: str = "wikipedia", endpoint: str = "") -> dict[str, Any]:
        if not query.strip() or len(query) > 256 or contains_secret(query):
            raise InternetError("INTERNET.QUERY_DENIED")
        if provider in {"hackernews", "searxng"}:
            return self.json_search(query, provider, endpoint)
        if provider != "wikipedia":
            raise InternetError("INTERNET.SEARCH_PROVIDER_DENIED")
        url = "https://en.wikipedia.org/w/api.php?" + urlencode(
            {
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": 5,
                "format": "json",
                "utf8": 1,
            }
        )
        reply = self.network.request(url)
        try:
            if reply.status != 200:
                raise ValueError()
            results = json.loads(reply.body)["query"]["search"]
            sources = []
            for value in results[:5]:
                snippet = Document()
                snippet.feed(str(value["snippet"]))
                sources.append(
                    {
                        "title": str(value["title"])[:300],
                        "url": "https://en.wikipedia.org/?"
                        + urlencode({"curid": int(value["pageid"])}),
                        "text": " ".join(snippet.parts)[:2000],
                        "updated_at": value.get("timestamp"),
                        "fetched_at": reply.fetched_at,
                        "source_kind": "WEB",
                        "trust": "UNTRUSTED_DATA",
                        "epistemic_status": "RETRIEVED",
                    }
                )
            if contains_secret(json.dumps(sources)):
                raise InternetError("INTERNET.SECRET_OUTPUT_DENIED")
            return {
                "provider": "Wikipedia full-text search",
                "sources": sources,
                "answer": "Retrieved excerpts; no generated claims or local-memory evidence.",
                "freshness": "LIVE_FETCH; publication accuracy unverified",
            }
        except (ValueError, KeyError, TypeError):
            raise InternetError("INTERNET.SEARCH_UNAVAILABLE") from None

    def json_search(self, query: str, provider: str, endpoint: str) -> dict[str, Any]:
        if provider == "hackernews":
            url = "https://hn.algolia.com/api/v1/search?" + urlencode(
                {
                    "query": query,
                    "tags": "story",
                    "hitsPerPage": 5,
                }
            )
            label = "Hacker News via Algolia; technology/community stories"
        else:
            base = safe_url(endpoint)
            if "?" in base:
                raise InternetError("INTERNET.URL_DENIED")
            url = base + "?" + urlencode({"q": query, "format": "json"})
            label = "Owner-selected SearXNG; engine coverage depends on that instance"
        reply = self.network.request(url, redirects=False)
        try:
            if reply.status != 200 or "application/json" not in reply.headers.get(
                "content-type", ""
            ):
                raise ValueError()
            values = json.loads(reply.body)["hits" if provider == "hackernews" else "results"]
            if not isinstance(values, list):
                raise ValueError()
            sources = []
            for item in values[:5]:
                result_url = (
                    "https://news.ycombinator.com/item?" + urlencode({"id": item["objectID"]})
                    if provider == "hackernews"
                    else safe_url(str(item["url"]))
                )
                parser = Document()
                parser.feed(str(item.get("content", item.get("story_text") or "")))
                sources.append(
                    {
                        "title": str(item.get("title", ""))[:300],
                        "url": result_url,
                        "text": " ".join(parser.parts)[:2000] or str(item.get("title", ""))[:2000],
                        "published_at": item.get("created_at", item.get("publishedDate")),
                        "fetched_at": reply.fetched_at,
                        "source_kind": "WEB",
                        "trust": "UNTRUSTED_DATA",
                        "epistemic_status": "RETRIEVED",
                    }
                )
            if contains_secret(json.dumps(sources)):
                raise InternetError("INTERNET.SECRET_OUTPUT_DENIED")
            return {
                "provider": label,
                "sources": sources,
                "answer": "Retrieved excerpts; no generated claims or local-memory evidence.",
                "freshness": "LIVE_FETCH of search index; result dates and index lag unverified",
            }
        except (ValueError, KeyError, TypeError):
            raise InternetError("INTERNET.SEARCH_UNAVAILABLE") from None
