"""Return randomized webcam landmarks for the world-at-glance section.

This tool intentionally serves a global pool rather than matching the user's
city. The digest section is meant to feel like a quick world window, so the
location input is only echoed back as metadata for the caller.
"""

import asyncio
import random
from typing import Dict, List, Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field


GLOBAL_FALLBACK_LANDMARKS = [
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
    {
        "name": "Eiffel Tower",
        "image": "",
        "stream": "https://www.earthcam.com/world/france/paris/?cam=toureiffel",
    },
    {
        "name": "Times Square",
        "image": "",
        "stream": "https://www.earthcam.com/usa/newyork/timessquare/?cam=tsrobo1",
    },
    {
        "name": "Venice Grand Canal",
        "image": "",
        "stream": "https://www.earthcam.com/world/italy/venice/",
    },
    {
        "name": "Tokyo Shibuya Crossing",
        "image": "",
        "stream": "https://www.earthcam.com/world/japan/tokyo/?cam=shibuya",
    },
    {
        "name": "Dublin Temple Bar",
        "image": "",
        "stream": "https://www.earthcam.com/world/ireland/dublin/?cam=templebar",
    },
    {
        "name": "Istanbul Hagia Sophia",
        "image": "",
        "stream": "https://www.earthcam.com/world/turkey/istanbul/?cam=hagiasophia",
    },
    {
        "name": "Rome Trevi Fountain",
        "image": "",
        "stream": "https://www.skylinewebcams.com/en/webcam/italia/lazio/roma/fontana-di-trevi.html",
    },
    {
        "name": "New Orleans Bourbon Street",
        "image": "",
        "stream": "https://www.earthcam.com/usa/louisiana/neworleans/bourbonstreet/",
    },
    {
        "name": "Niagara Falls",
        "image": "",
        "stream": "https://www.earthcam.com/world/canada/niagarafalls/",
    },
]
LANDMARK_SAMPLE_SIZE = 6


class CityCameraInput(BaseModel):
    location: str = Field(..., description="City name")


class FetchCityLandmarksTool(BaseTool):
    name: str = "fetch_city_landmarks"
    description: str = "Retrieve three live landmark webcams from around the world"
    args_schema: Type[BaseModel] = CityCameraInput

    def _normalized_location(self, location: str) -> str:
        """Normalize the incoming location for metadata only."""
        return (location or "").strip().lower()

    def _shuffled_landmarks(self) -> List[Dict]:
        """Return the global fallback pool in randomized order."""
        webcams = GLOBAL_FALLBACK_LANDMARKS[:]
        random.SystemRandom().shuffle(webcams)
        return webcams

    def _selected_landmarks(self) -> List[Dict]:
        """Return the subset exposed to the world-at-glance renderer."""
        return self._shuffled_landmarks()[:LANDMARK_SAMPLE_SIZE]

    def _run(self, location: str) -> Dict:
        """Return a small randomized set of landmark webcam links."""
        return {
            "city": self._normalized_location(location),
            "landmarks": self._selected_landmarks(),
        }

    async def arun(self, location: str) -> Dict:
        """Run the landmark fetch without blocking the event loop."""
        return await asyncio.to_thread(self.run, location=location)
