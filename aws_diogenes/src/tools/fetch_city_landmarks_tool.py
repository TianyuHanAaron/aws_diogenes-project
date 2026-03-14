import random
from typing import Dict, List, Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field


CITY_WEBCAMS = {
    "sydney": [
        {
            "name": "Sydney Opera House and Harbour Bridge",
            "image": "https://images.webcamsydney.com/sydney-harbour.jpg",
            "stream": "https://www.webcamsydney.com/",
        },
        {
            "name": "Bondi Beach",
            "image": "https://bondisurfclub.com/wp-content/uploads/bondi-surf-cam.jpg",
            "stream": "https://bondisurfclub.com/bondi-surf-cam/",
        },
        {
            "name": "Manly Beach",
            "image": "https://worldcam.eu/webcams/australia-oceania/sydney/35769-manly-beach.jpg",
            "stream": "https://worldcam.eu/webcams/australia-oceania/sydney/35769-manly-beach",
        },
    ],
    "paris": [
        {
            "name": "Eiffel Tower",
            "image": "https://static.skylinewebcams.com/webcam/france/ile-de-france/paris/eiffel-tower.jpg",
            "stream": "https://www.skylinewebcams.com/en/webcam/france/ile-de-france/paris/eiffel-tower.html",
        },
        {
            "name": "Notre Dame Cathedral",
            "image": "https://static.skylinewebcams.com/webcam/france/paris/notre-dame.jpg",
            "stream": "https://www.skylinewebcams.com/en/webcam/france/paris/notre-dame.html",
        },
        {
            "name": "Montmartre",
            "image": "https://static.skylinewebcams.com/webcam/france/paris/montmartre.jpg",
            "stream": "https://www.skylinewebcams.com/en/webcam/france/paris/montmartre.html",
        },
    ],
}

GLOBAL_FALLBACK_LANDMARKS = [
    landmark
    for city_landmarks in CITY_WEBCAMS.values()
    for landmark in city_landmarks
]


class CityCameraInput(BaseModel):
    location: str = Field(..., description="City name")


class FetchCityLandmarksTool(BaseTool):
    name: str = "fetch_city_landmarks"
    description: str = "Retrieve three live landmark webcams for a city"
    args_schema: Type[BaseModel] = CityCameraInput

    def _run(self, location: str) -> Dict:
        city = (location or "").strip().lower()
        webcams = CITY_WEBCAMS.get(city, [])
        if not webcams:
            shuffled = GLOBAL_FALLBACK_LANDMARKS[:]
            random.Random(city or "world").shuffle(shuffled)
            webcams = shuffled[:3]
        return {
            "city": city,
            "landmarks": webcams[:3],
        }
