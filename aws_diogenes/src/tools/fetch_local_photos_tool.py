from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Dict, List, Type

from tools._data import load_mock_data


class FetchLocalPhotosInput(BaseModel):
    location: str = Field(..., description="User city or region")


class FetchLocalPhotosTool(BaseTool):
    name: str = "fetch_local_photos"
    description: str = "Retrieve candidate local photographs"
    args_schema: Type[BaseModel] = FetchLocalPhotosInput

    def _run(self, location: str) -> List[Dict]:
        photos = load_mock_data("mock_photos.json")

        return [p for p in photos if p["location"] == location]
