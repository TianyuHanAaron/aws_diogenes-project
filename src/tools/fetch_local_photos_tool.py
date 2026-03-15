"""Fetch city photography candidates from image providers.

The photo album section uses this module as a broad upstream collector. Each
provider keeps its native payload shape here, and the album workflow chooses
and normalizes the final cards later.
"""

import asyncio
import logging
from typing import Any, Callable, Dict, List, Type

import requests
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from settings import (
    PEXELS_API_KEY,
    UNSPLASH_ACCESS_KEY,
    PIXABAY_KEY
)


logger = logging.getLogger(__name__)
PhotoResult = Dict[str, Any]
PHOTO_SOURCE_QUERIES = ("street", "skyline", "waterfront", "beach", "sunset")


class FetchLocalPhotosInput(BaseModel):
    location: str = Field(..., description="City or region")


class FetchLocalPhotosTool(BaseTool):
    name: str = "fetch_local_photos"
    description: str = "Retrieve local photos from multiple sources"
    args_schema: Type[BaseModel] = FetchLocalPhotosInput

    def _normalized_location(self, location: str) -> str:
        """Normalize the location text before it is used in provider queries."""
        return (location or "").strip()

    def _queries(self, location: str) -> List[str]:
        """Expand one location into a small set of scene-oriented searches."""
        base = self._normalized_location(location)
        if not base:
            return []
        return [base, *[f"{base} {suffix}" for suffix in PHOTO_SOURCE_QUERIES]]

    def _get_json(self, url: str, *, params: dict | None = None, headers: dict | None = None) -> dict:
        """Fetch one JSON endpoint and return the parsed payload."""
        response = requests.get(url, params=params, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()

    def _pexels_params(self, query: str) -> dict:
        """Build the Pexels search params in one place."""
        return {"query": query, "per_page": 8}

    def _unsplash_params(self, query: str) -> dict:
        """Build the Unsplash search params in one place."""
        return {"query": query, "client_id": UNSPLASH_ACCESS_KEY, "per_page": 8}

    def _pixabay_params(self, query: str) -> dict:
        """Build the Pixabay search params in one place."""
        return {"key": PIXABAY_KEY, "q": query, "image_type": "photo", "per_page": 8}

    def fetch_pexels(self, query: str) -> List[PhotoResult]:
        """Fetch Pexels results for one query string."""
        return self._get_json(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": PEXELS_API_KEY},
            params=self._pexels_params(query),
        ).get("photos", [])

    def fetch_unsplash(self, query: str) -> List[PhotoResult]:
        """Fetch Unsplash results for one query string."""
        return self._get_json(
            "https://api.unsplash.com/search/photos",
            params=self._unsplash_params(query),
        ).get("results", [])

    def fetch_pixabay(self, query: str) -> List[PhotoResult]:
        """Fetch Pixabay results for one query string."""
        return self._get_json(
            "https://pixabay.com/api/",
            params=self._pixabay_params(query),
        ).get("hits", [])

    def _photo_id(self, item: PhotoResult) -> Any:
        """Return the provider-specific identifier used for lightweight deduping."""
        return item.get("id") or item.get("photo_id")

    def _append_unique_items(
        self,
        photos: List[PhotoResult],
        seen_ids: set[Any],
        items: List[PhotoResult],
    ) -> None:
        """Merge items into the result list while skipping duplicate provider ids."""
        for item in items:
            photo_id = self._photo_id(item)
            if photo_id and photo_id in seen_ids:
                continue
            if photo_id:
                seen_ids.add(photo_id)
            photos.append(item)

    def _collect_source_results(
        self,
        photos: List[PhotoResult],
        seen_ids: set[Any],
        *,
        source_name: str,
        fetcher: Callable[[str], List[PhotoResult]],
        queries: List[str],
    ) -> None:
        """Run one provider across all queries while keeping failures non-fatal."""
        for query in queries:
            try:
                self._append_unique_items(photos, seen_ids, fetcher(query))
            except Exception as exc:
                logger.warning("%s photo fetch failed for %s: %s", source_name, query, exc)

    def _provider_fetchers(self) -> List[tuple[str, Callable[[str], List[PhotoResult]]]]:
        """Return the configured image providers in the order we want to query them."""
        return [
            ("Pexels", self.fetch_pexels),
            ("Unsplash", self.fetch_unsplash),
            ("Pixabay", self.fetch_pixabay),
        ]

    def _run(self, location: str) -> List[PhotoResult]:
        """Collect photos from all configured providers."""
        photos: List[PhotoResult] = []
        seen_ids: set[Any] = set()
        queries = self._queries(location)

        for source_name, fetcher in self._provider_fetchers():
            self._collect_source_results(
                photos,
                seen_ids,
                source_name=source_name,
                fetcher=fetcher,
                queries=queries,
            )
        return photos

    async def arun(self, location: str) -> List[Dict]:
        """Run the photo fetch without blocking the event loop."""
        return await asyncio.to_thread(self.run, location=location)
