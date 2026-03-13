import os
from typing import Dict, List, Type

import requests

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from tools._data import load_mock_data


class FetchNewsInput(BaseModel):
    topic: str = Field(..., description="News search topic")


class FetchNewsTool(BaseTool):

    name: str = "fetch_news"
    description: str = "Fetch news articles from API or mock dataset"

    args_schema: Type[BaseModel] = FetchNewsInput

    def _run(self, topic: str) -> List[Dict]:

        api_key = os.getenv("NEWSAPI_API_KEY") or os.getenv("NEWS_API_KEY")

        if api_key:
            try:
                response = requests.get(
                    "https://newsapi.org/v2/everything",
                    params={
                        "q": topic,
                        "language": "en",
                        "pageSize": 20,
                        "apiKey": api_key
                    },
                    timeout=10
                )

                if response.status_code == 200:
                    data = response.json()

                    articles = []

                    for a in data.get("articles", []):
                        articles.append({
                            "title": a["title"],
                            "content": a["description"],
                            "source": a["source"]["name"]
                        })

                    return articles

            except Exception:
                pass

        return load_mock_data("mock_news.json")
