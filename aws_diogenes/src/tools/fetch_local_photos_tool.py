import os
import requests

from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Dict, List, Type

from tools._data import load_mock_data


class FetchLocalPhotosInput(BaseModel):
    location: str = Field(..., description="User city or region")


class FetchLocalPhotosTool(BaseTool):

    name: str = "fetch_local_photos"
    description: str = "Retrieve candidate local photographs from API or mock data"

    args_schema: Type[BaseModel] = FetchLocalPhotosInput

    def _run(self, location: str) -> List[Dict]:

        api_key = os.getenv("PEXELS_API_KEY")

        # If API key exists → use real API
        if api_key:
            try:
                url = "https://api.pexels.com/v1/search"

                headers = {
                    "Authorization": api_key
                }

                params = {
                    "query": location,
                    "per_page": 15
                }

                response = requests.get(url, headers=headers, params=params, timeout=10)

                if response.status_code == 200:

                    data = response.json()

                    photos = []

                    for p in data.get("photos", []):
                        photos.append({
                            "photo_id": p["id"],
                            "url": p["src"]["large"],
                            "photographer": p["photographer"],
                            "location": location
                        })

                    return photos

            except Exception:
                pass

        # Fallback → mock data
        photos = load_mock_data("mock_photos.json")

        return [p for p in photos if p["location"] == location]