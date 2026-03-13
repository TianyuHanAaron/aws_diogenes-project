from crewai.tools import BaseTool
import os
from typing import Dict, List, Type

import requests
from pydantic import BaseModel, Field

class FetchNewsInput(BaseModel):
    topic: str = Field(..., description="Topic or keyword to search for news articles")


class FetchNewsTool(BaseTool):
    name: str = "fetch_news"
    description: str = "Fetch recent news articles related to a topic"
    args_schema: Type[BaseModel] = FetchNewsInput

    def _run(self, topic: str) -> List[Dict]:
        api_key = os.getenv("NEWSAPI_API_KEY")
        if not api_key:
            raise RuntimeError("NEWSAPI_API_KEY is not set")

        params = {
            "q": topic,
            "language": "en",
            "pageSize": 10,
            "apiKey": api_key,
        }

        response = requests.get(
            "https://newsapi.org/v2/everything",
            params=params,
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("status") != "ok":
            raise RuntimeError(data.get("message", "News API request failed"))

        articles = []

        for article in data.get("articles", []):
            articles.append({
                "title": article.get("title"),
                "content": article.get("description"),
                "source": article.get("source", {}).get("name")
            })

        return articles
