from crewai.tools import BaseTool
from pydantic import BaseModel, Field, model_validator
from typing import List, Dict, Type
import logging

import requests
import feedparser

from settings import NEWSAPI_API_KEY, GUARDIAN_KEY


logger = logging.getLogger(__name__)


class FetchNewsInput(BaseModel):
    query: str = Field(default="", description="Topic to search for news")
    topic: str = Field(default="", description="Backward-compatible alias for query")

    @model_validator(mode="after")
    def ensure_query(self):
        if not self.query and self.topic:
            self.query = self.topic
        if not self.query:
            raise ValueError("query is required")
        return self


class FetchNewsTool(BaseTool):

    name: str = "fetch_news"
    description: str = "Retrieve news from multiple APIs and RSS feeds"
    args_schema: Type[BaseModel] = FetchNewsInput

    def fetch_newsapi(self, query):

        url = "https://newsapi.org/v2/everything"

        params = {
            "q": query,
            "apiKey": NEWSAPI_API_KEY,
            "pageSize": 20,
            "language": "en"
        }

        r = requests.get(url, params=params)
        data = r.json()

        articles = []

        for item in data.get("articles", []):

            articles.append({
                "title": item.get("title"),
                "summary": item.get("description"),
                "url": item.get("url"),
                "source": item.get("source", {}).get("name"),
                "published": item.get("publishedAt")
            })

        return articles


    def fetch_guardian(self, query):

        url = "https://content.guardianapis.com/search"

        params = {
            "q": query,
            "api-key": GUARDIAN_KEY,
            "page-size": 20
        }

        r = requests.get(url, params=params)
        data = r.json()

        results = data.get("response", {}).get("results", [])

        articles = []

        for item in results:

            articles.append({
                "title": item.get("webTitle"),
                "summary": "",
                "url": item.get("webUrl"),
                "source": "Guardian",
                "published": item.get("webPublicationDate")
            })

        return articles


    def fetch_rss(self):

        feeds = [
            "https://feeds.bbci.co.uk/news/rss.xml",
            "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
            "https://www.reutersagency.com/feed/"
        ]

        articles = []

        for url in feeds:

            feed = feedparser.parse(url)

            for entry in feed.entries:

                articles.append({
                    "title": entry.get("title"),
                    "summary": entry.get("summary"),
                    "url": entry.get("link"),
                    "source": feed.feed.get("title"),
                    "published": entry.get("published", "")
                })

        return articles


    def _run(self, query: str = "", topic: str = "") -> List[Dict]:

        query = query or topic

        results = []

        try:
            results.extend(self.fetch_newsapi(query))
        except Exception as exc:
            logger.warning("NewsAPI fetch failed for %s: %s", query, exc)

        try:
            results.extend(self.fetch_guardian(query))
        except Exception as exc:
            logger.warning("Guardian fetch failed for %s: %s", query, exc)

        try:
            results.extend(self.fetch_rss())
        except Exception as exc:
            logger.warning("RSS fetch failed: %s", exc)

        return results
