from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import List, Dict, Type
import logging

import requests

from settings import (
    PEXELS_API_KEY,
    UNSPLASH_ACCESS_KEY,
    PIXABAY_KEY
)


logger = logging.getLogger(__name__)


class FetchLocalPhotosInput(BaseModel):
    location: str = Field(..., description="City or region")


class FetchLocalPhotosTool(BaseTool):

    name: str = "fetch_local_photos"
    description: str = "Retrieve local photos from multiple sources"
    args_schema: Type[BaseModel] = FetchLocalPhotosInput


    def fetch_pexels(self, location):

        url = "https://api.pexels.com/v1/search"

        headers = {
            "Authorization": PEXELS_API_KEY
        }

        params = {
            "query": location,
            "per_page": 15
        }

        r = requests.get(url, headers=headers, params=params)

        return r.json().get("photos", [])


    def fetch_unsplash(self, location):

        url = "https://api.unsplash.com/search/photos"

        params = {
            "query": location,
            "client_id": UNSPLASH_ACCESS_KEY,
            "per_page": 15
        }

        r = requests.get(url, params=params)

        return r.json().get("results", [])


    def fetch_pixabay(self, location):

        url = "https://pixabay.com/api/"

        params = {
            "key": PIXABAY_KEY,
            "q": location,
            "image_type": "photo",
            "per_page": 15
        }

        r = requests.get(url, params=params)

        return r.json().get("hits", [])


    def _run(self, location: str) -> List[Dict]:

        photos = []

        try:
            photos.extend(self.fetch_pexels(location))
        except Exception as exc:
            logger.warning("Pexels photo fetch failed for %s: %s", location, exc)

        try:
            photos.extend(self.fetch_unsplash(location))
        except Exception as exc:
            logger.warning("Unsplash photo fetch failed for %s: %s", location, exc)

        try:
            photos.extend(self.fetch_pixabay(location))
        except Exception as exc:
            logger.warning("Pixabay photo fetch failed for %s: %s", location, exc)

        return photos
