"""Fetch news from API and RSS sources."""

import asyncio
import logging
from typing import Dict, List, Type

import requests
import feedparser
from crewai.tools import BaseTool
from pydantic import BaseModel, Field, model_validator

from settings import NEWSAPI_API_KEY, GUARDIAN_KEY


logger = logging.getLogger(__name__)
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

    def fetch_newsapi(self, query: str) -> List[Dict]:
        """Fetch stories from NewsAPI and map them into the shared article shape."""
        data = self._get_json("https://newsapi.org/v2/everything", params=self._newsapi_params(query))
        return [
            {
                "title": item.get("title"),
                "summary": item.get("description"),
                "body": item.get("content") or item.get("description"),
                "url": item.get("url"),
                "source": item.get("source", {}).get("name"),
                "published": item.get("publishedAt"),
            }
            for item in data.get("articles", [])
        ]

    def fetch_guardian(self, query: str) -> List[Dict]:
        """Fetch stories from the Guardian search API."""
        data = self._get_json("https://content.guardianapis.com/search", params=self._guardian_params(query))
        return [
            {
                "title": item.get("webTitle"),
                "summary": item.get("fields", {}).get("trailText", ""),
                "body": item.get("fields", {}).get("bodyText", "") or item.get("fields", {}).get("trailText", ""),
                "url": item.get("webUrl"),
                "source": "Guardian",
                "published": item.get("webPublicationDate"),
            }
            for item in data.get("response", {}).get("results", [])
        ]

    def fetch_rss(self) -> List[Dict]:
        """Fetch stories from the RSS fallback feeds."""
        articles: List[Dict] = []
        for url in RSS_FEEDS:
            feed = feedparser.parse(url)
            articles.extend(
                {
                    "title": entry.get("title"),
                    "summary": entry.get("summary"),
                    "body": self._rss_body(entry),
                    "url": entry.get("link"),
                    "source": feed.feed.get("title"),
                    "published": entry.get("published", ""),
                }
                for entry in feed.entries
            )
        return articles

    def _rss_body(self, entry) -> str:
        """Extract the richest available body-like text from an RSS entry."""
        content = entry.get("content", [])
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict):
                return str(first.get("value", "") or entry.get("summary", ""))
        return str(entry.get("summary", "") or "")

    def _extend_results(self, results: List[Dict], label: str, fetcher, *args) -> None:
        """Append one source's stories while keeping fetch errors non-fatal."""
        try:
            results.extend(fetcher(*args))
        except Exception as exc:
            logger.warning("%s fetch failed: %s", label, exc)

    def _run(self, query: str = "", topic: str = "") -> List[Dict]:
        """Collect news from all configured sources."""
        query = query or topic
        results: List[Dict] = []

        self._extend_results(results, f"NewsAPI fetch failed for {query}", self.fetch_newsapi, query)
        self._extend_results(results, f"Guardian fetch failed for {query}", self.fetch_guardian, query)
        self._extend_results(results, "RSS fetch failed", self.fetch_rss)
        return results

    async def arun(self, query: str = "", topic: str = "") -> List[Dict]:
        """Run the news fetch without blocking the event loop."""
        return await asyncio.to_thread(self.run, query=query, topic=topic)
