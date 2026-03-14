from typing import Dict, List, Type
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from crewai.tools import BaseTool
from pydantic import BaseModel, Field
import requests

from settings import FIRECRAWL_API_KEY


logger = logging.getLogger(__name__)


class FetchSeasonalEventsInput(BaseModel):
    location: str = Field(..., description="User country, city, or region")
    hemisphere: str = Field(..., description="User hemisphere: northern or southern")
    month: str = Field(..., description="Current month in full text, for example March")


class FetchSeasonalEventsTool(BaseTool):
    name: str = "fetch_seasonal_events"
    description: str = (
        "Retrieve real-time seasonal, celestial, blossom, migration, and festival "
        "information from trusted public web sources."
    )
    args_schema: Type[BaseModel] = FetchSeasonalEventsInput

    def _run(self, location: str, hemisphere: str, month: str) -> List[Dict]:
        if not FIRECRAWL_API_KEY:
            logger.warning("FIRECRAWL_API_KEY is not set; seasonal events search will be skipped")
            return []

        year = datetime.now(ZoneInfo("Australia/Sydney")).year

        queries = [
            f"{location} festivals {month} {year}",
            f"{location} events {month} {year}",
            f"{location} holidays {month} {year} site:timeanddate.com",
            f"{hemisphere} hemisphere skywatching {month} site:nasa.gov",
            f"meteor showers {month} {year} site:amsmeteors.org",
            f"{location} blossom season {month}",
            f"{location} flower bloom season {month}",
            f"{location} bird migration season {month}",
        ]

        results: List[Dict] = []

        for query in queries:
            try:
                response = requests.post(
                    "https://api.firecrawl.dev/v1/search",
                    headers={
                        "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "query": query,
                        "limit": 3,
                        "location": location,
                        "ignoreInvalidURLs": True,
                        "scrapeOptions": {
                            "formats": ["markdown"],
                        },
                    },
                    timeout=60,
                )
                response.raise_for_status()
                search_result = response.json()
                results.append(
                    {
                        "query": query,
                        "content": search_result.get("data", []),
                    }
                )
            except Exception as exc:
                logger.warning("Seasonal events query failed for %s: %s", query, exc)
                continue

        return results
