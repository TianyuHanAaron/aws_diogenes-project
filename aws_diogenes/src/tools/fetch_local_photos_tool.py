"""Fetch city photography candidates from image providers."""

import asyncio
import logging
from typing import Dict, List, Type

import requests
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from settings import (
    PEXELS_API_KEY,
    UNSPLASH_ACCESS_KEY,
    PIXABAY_KEY
)


logger = logging.getLogger(__name__)
PHOTO_SOURCE_QUERIES = ("street", "skyline", "waterfront", "beach", "sunset")


class FetchLocalPhotosInput(BaseModel):
    location: str = Field(..., description="City or region")


class FetchLocalPhotosTool(BaseTool):
    name: str = "fetch_local_photos"
    description: str = "Retrieve local photos from multiple sources"
    args_schema: Type[BaseModel] = FetchLocalPhotosInput

    def _queries(self, location: str) -> List[str]:
        """Expand one location into a small set of scene-oriented searches."""
        base = (location or "").strip()
        if not base:
            return []
        return [base, *[f"{base} {suffix}" for suffix in PHOTO_SOURCE_QUERIES]]

    def _get_json(self, url: str, *, params: dict | None = None, headers: dict | None = None) -> dict:
        """Fetch one JSON endpoint and return the parsed payload."""
        response = requests.get(url, params=params, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()

    def fetch_pexels(self, query: str) -> List[Dict]:
        """Fetch Pexels results for one query string."""
        return self._get_json(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": PEXELS_API_KEY},
            params={"query": query, "per_page": 8},
        ).get("photos", [])

    def fetch_unsplash(self, query: str) -> List[Dict]:
        """Fetch Unsplash results for one query string."""
        return self._get_json(
            "https://api.unsplash.com/search/photos",
            params={"query": query, "client_id": UNSPLASH_ACCESS_KEY, "per_page": 8},
        ).get("results", [])

    def fetch_pixabay(self, query: str) -> List[Dict]:
        """Fetch Pixabay results for one query string."""
        return self._get_json(
            "https://pixabay.com/api/",
            params={"key": PIXABAY_KEY, "q": query, "image_type": "photo", "per_page": 8},
        ).get("hits", [])

    def _append_unique_items(self, photos: List[Dict], seen_ids: set, items: List[Dict]) -> None:
        """Merge items into the result list while skipping duplicate provider ids."""
        for item in items:
            photo_id = item.get("id") or item.get("photo_id")
            if photo_id and photo_id in seen_ids:
                continue
            if photo_id:
                seen_ids.add(photo_id)
            photos.append(item)

    def _collect_source_results(self, photos: List[Dict], seen_ids: set, source_name: str, fetcher, queries: List[str]) -> None:
        """Run one provider across all queries while keeping failures non-fatal."""
        for query in queries:
            try:
                self._append_unique_items(photos, seen_ids, fetcher(query))
            except Exception as exc:
                logger.warning("%s photo fetch failed for %s: %s", source_name, query, exc)

    def _run(self, location: str) -> List[Dict]:
        """Collect photos from all configured providers."""
        photos: List[Dict] = []
        seen_ids: set = set()
        queries = self._queries(location)

        self._collect_source_results(photos, seen_ids, "Pexels", self.fetch_pexels, queries)
        self._collect_source_results(photos, seen_ids, "Unsplash", self.fetch_unsplash, queries)
        self._collect_source_results(photos, seen_ids, "Pixabay", self.fetch_pixabay, queries)
        return photos

    async def arun(self, location: str) -> List[Dict]:
        """Run the photo fetch without blocking the event loop."""
        return await asyncio.to_thread(self.run, location=location)
