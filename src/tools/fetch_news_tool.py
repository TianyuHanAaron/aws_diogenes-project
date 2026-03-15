"""Fetch news from API and RSS sources.

This module intentionally keeps the provider-specific mapping code small and
explicit. The rest of the app consumes a shared article shape, so each provider
adapter converts its payload into that common structure here.
"""

import asyncio
import logging
from typing import Any, Callable, Dict, List, Type

import feedparser
from crewai.tools import BaseTool
from pydantic import BaseModel, Field, model_validator
import requests

from settings import NEWSAPI_API_KEY, GUARDIAN_KEY


logger = logging.getLogger(__name__)
Article = Dict[str, Any]
RSS_FEEDS = [
    "https://feeds.bbci.co.uk/news/rss.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
    "https://www.reutersagency.com/feed/",
]


class FetchNewsInput(BaseModel):
    query: str = Field(default="", description="Topic to search for news")
    topic: str = Field(default="", description="Backward-compatible alias for query")

    @model_validator(mode="after")
    def ensure_query(self):
        """Allow `topic` as a backward-compatible alias for `query`."""
        if not self.query and self.topic:
            self.query = self.topic
        if not self.query:
            raise ValueError("query is required")
        return self


class FetchNewsTool(BaseTool):
    name: str = "fetch_news"
    description: str = "Retrieve news from multiple APIs and RSS feeds"
    args_schema: Type[BaseModel] = FetchNewsInput

    def _newsapi_params(self, query: str) -> dict:
        """Build the NewsAPI query parameters in one place."""
        return {
            "q": query,
            "apiKey": NEWSAPI_API_KEY,
            "pageSize": 20,
            "language": "en",
        }

    def _guardian_params(self, query: str) -> dict:
        """Build the Guardian API query parameters in one place."""
        return {
            "q": query,
            "api-key": GUARDIAN_KEY,
            "page-size": 20,
            "show-fields": "trailText,bodyText",
        }

    def _get_json(self, url: str, *, params: dict | None = None, headers: dict | None = None) -> dict:
        """Fetch one JSON endpoint and return the parsed payload."""
        response = requests.get(url, params=params, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()

    def _newsapi_article(self, item: dict) -> Article:
        """Map one NewsAPI article into the shared article shape."""
        return {
            "title": item.get("title"),
            "summary": item.get("description"),
            "body": item.get("content") or item.get("description"),
            "url": item.get("url"),
            "source": item.get("source", {}).get("name"),
            "published": item.get("publishedAt"),
        }

    def _guardian_article(self, item: dict) -> Article:
        """Map one Guardian search result into the shared article shape."""
        fields = item.get("fields", {})
        return {
            "title": item.get("webTitle"),
            "summary": fields.get("trailText", ""),
            "body": fields.get("bodyText", "") or fields.get("trailText", ""),
            "url": item.get("webUrl"),
            "source": "Guardian",
            "published": item.get("webPublicationDate"),
        }

    def _rss_article(self, *, feed_title: str, entry: dict) -> Article:
        """Map one RSS entry into the shared article shape."""
        return {
            "title": entry.get("title"),
            "summary": entry.get("summary"),
            "body": self._rss_body(entry),
            "url": entry.get("link"),
            "source": feed_title,
            "published": entry.get("published", ""),
        }

    def fetch_newsapi(self, query: str) -> List[Article]:
        """Fetch stories from NewsAPI and map them into the shared article shape."""
        data = self._get_json("https://newsapi.org/v2/everything", params=self._newsapi_params(query))
        return [self._newsapi_article(item) for item in data.get("articles", [])]

    def fetch_guardian(self, query: str) -> List[Article]:
        """Fetch stories from the Guardian search API."""
        data = self._get_json("https://content.guardianapis.com/search", params=self._guardian_params(query))
        return [self._guardian_article(item) for item in data.get("response", {}).get("results", [])]

    def fetch_rss(self) -> List[Article]:
        """Fetch stories from the RSS fallback feeds."""
        articles: List[Article] = []
        for url in RSS_FEEDS:
            feed = feedparser.parse(url)
            feed_title = str(feed.feed.get("title", ""))
            articles.extend(self._rss_article(feed_title=feed_title, entry=entry) for entry in feed.entries)
        return articles

    def _rss_body(self, entry) -> str:
        """Extract the richest available body-like text from an RSS entry."""
        content = entry.get("content", [])
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict):
                return str(first.get("value", "") or entry.get("summary", ""))
        return str(entry.get("summary", "") or "")

    def _article_key(self, item: Article) -> tuple[str, str, str]:
        """Build a stable key for de-duplicating articles across queries."""
        return (
            str(item.get("url", "") or "").strip().lower(),
            str(item.get("title", "") or "").strip().lower(),
            str(item.get("source", "") or "").strip().lower(),
        )

    def _append_unique_items(
        self,
        results: List[Article],
        items: List[Article],
        seen: set[tuple[str, str, str]],
    ) -> None:
        """Append only new articles while preserving order.

        We intentionally deduplicate on URL/title/source instead of provider
        IDs because the same story can be surfaced by different backends.
        """
        for item in items:
            if not isinstance(item, dict):
                continue
            key = self._article_key(item)
            if not any(key):
                continue
            if key in seen:
                continue
            seen.add(key)
            results.append(item)

    def _normalize_queries(self, queries: List[str]) -> List[str]:
        """Remove blanks while keeping the caller's query order intact."""
        return [str(query).strip() for query in queries if str(query).strip()]

    def _is_rate_limited(self, exc: Exception) -> bool:
        """Identify provider responses that should stop further requests this run."""
        if not isinstance(exc, requests.HTTPError):
            return False
        response = getattr(exc, "response", None)
        return getattr(response, "status_code", None) == 429

    def _collect_provider_results(
        self,
        results: List[Article],
        seen: set[tuple[str, str, str]],
        *,
        provider_name: str,
        query: str,
        fetcher: Callable[[str], List[Article]],
    ) -> bool:
        """Run one query against one search provider and keep failures non-fatal.

        Returns `False` when the provider should be skipped for the rest of the
        current run, which we use for rate-limit responses like HTTP 429.
        """
        try:
            self._append_unique_items(results, fetcher(query), seen)
            return True
        except Exception as exc:
            if self._is_rate_limited(exc):
                logger.warning("%s rate limited; skipping remaining %s queries for this run", provider_name, provider_name)
                return False
            logger.warning("%s fetch failed for %s: %s", provider_name, query, exc)
            return True

    def _collect_search_results(
        self,
        results: List[Article],
        seen: set[tuple[str, str, str]],
        query: str,
        disabled_providers: set[str],
    ) -> None:
        """Collect the API-backed providers for one query string.

        This keeps the broadening logic easy to read: for each search idea, ask
        both API providers before moving on to the next idea.
        """
        for provider_name, fetcher in (
            ("NewsAPI", self.fetch_newsapi),
            ("Guardian", self.fetch_guardian),
        ):
            if provider_name in disabled_providers:
                continue
            keep_provider_enabled = self._collect_provider_results(
                results,
                seen,
                provider_name=provider_name,
                query=query,
                fetcher=fetcher,
            )
            if not keep_provider_enabled:
                disabled_providers.add(provider_name)

    def _collect_rss_results(
        self,
        results: List[Article],
        seen: set[tuple[str, str, str]],
    ) -> None:
        """Append the RSS fallback pool once after the query-driven sources."""
        try:
            self._append_unique_items(results, self.fetch_rss(), seen)
        except Exception as exc:
            logger.warning("RSS fetch failed: %s", exc)

    def fetch_queries(self, queries: List[str]) -> List[Article]:
        """Fetch a broader news pool from several search queries plus one RSS pass."""
        results: List[Article] = []
        seen: set[tuple[str, str, str]] = set()
        disabled_providers: set[str] = set()
        unique_queries = self._normalize_queries(queries)

        for query in unique_queries:
            self._collect_search_results(results, seen, query, disabled_providers)

        self._collect_rss_results(results, seen)
        return results

    def _run(self, query: str = "", topic: str = "") -> List[Dict]:
        """Collect news from all configured sources."""
        query = query or topic
        return self.fetch_queries([query])

    async def arun(self, query: str = "", topic: str = "") -> List[Dict]:
        """Run the news fetch without blocking the event loop."""
        return await asyncio.to_thread(self.run, query=query, topic=topic)

    async def arun_queries(self, queries: List[str]) -> List[Dict]:
        """Run a multi-query news fetch without blocking the event loop."""
        return await asyncio.to_thread(self.fetch_queries, queries)
