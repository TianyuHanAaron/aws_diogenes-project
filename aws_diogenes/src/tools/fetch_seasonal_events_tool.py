"""Fetch seasonal event source material from Firecrawl search."""

import asyncio
from datetime import datetime, timedelta
import logging
from typing import Dict, List, Type
from zoneinfo import ZoneInfo

import requests
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from settings import FIRECRAWL_API_KEY


logger = logging.getLogger(__name__)
FIRECRAWL_SEARCH_URL = "https://api.firecrawl.dev/v1/search"


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

    def _build_queries(self, location: str, hemisphere: str, month: str, year: int, now: datetime, window_end: datetime) -> List[str]:
        """Build the search queries used to find upcoming seasonal material."""
        return [
            f"public holidays worldwide {now.strftime('%Y-%m-%d')} to {window_end.strftime('%Y-%m-%d')} site:timeanddate.com",
            f"public holidays around the world {month} {year} site:officeholidays.com",
            f"{location} public holidays {month} {year}",
            f"{location} festivals {month} {year}",
            f"{location} seasonal events {month} {year}",
            f"{hemisphere} hemisphere skywatching {month} {year} site:nasa.gov",
            f"meteor showers {month} {year} site:amsmeteors.org",
        ]

    def _request_payload(self, query: str, location: str) -> dict:
        """Build the Firecrawl request payload for one query."""
        return {
            "query": query,
            "limit": 3,
            "location": location,
            "ignoreInvalidURLs": True,
            "scrapeOptions": {
                "formats": ["markdown"],
            },
        }

    def _search_query(self, query: str, location: str) -> Dict:
        """Run one Firecrawl search query and normalize the result shape."""
        response = requests.post(
            FIRECRAWL_SEARCH_URL,
            headers={
                "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
                "Content-Type": "application/json",
            },
            json=self._request_payload(query, location),
            timeout=60,
        )
        response.raise_for_status()
        search_result = response.json()
        return {
            "query": query,
            "content": search_result.get("data", []),
        }

    def _run(self, location: str, hemisphere: str, month: str) -> List[Dict]:
        """Collect seasonal search results across the current digest window."""
        if not FIRECRAWL_API_KEY:
            logger.warning("FIRECRAWL_API_KEY is not set; seasonal events search will be skipped")
            return []

        now = datetime.now(ZoneInfo("Australia/Sydney"))
        year = now.year
        window_end = now + timedelta(days=14)
        queries = self._build_queries(location, hemisphere, month, year, now, window_end)

        results: List[Dict] = []

        for query in queries:
            try:
                results.append(self._search_query(query, location))
            except Exception as exc:
                logger.warning("Seasonal events query failed for %s: %s", query, exc)
                continue

        return results

    async def arun(self, location: str, hemisphere: str, month: str) -> List[Dict]:
        """Run the seasonal fetch without blocking the event loop."""
        return await asyncio.to_thread(
            self.run,
            location=location,
            hemisphere=hemisphere,
            month=month,
        )
