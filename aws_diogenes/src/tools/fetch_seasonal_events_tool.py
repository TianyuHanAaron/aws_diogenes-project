from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Dict, List, Type

from tools._data import load_mock_data


class FetchSeasonalEventsInput(BaseModel):
    location: str = Field(..., description="User location")


class FetchSeasonalEventsTool(BaseTool):
    name: str = "fetch_seasonal_events"
    description: str = "Retrieve seasonal and celestial events for a location"
    args_schema: Type[BaseModel] = FetchSeasonalEventsInput

    def _run(self, location: str) -> List[Dict]:
        events = load_mock_data("mock_seasonal_events.json")

        relevant = [e for e in events if e["location"] == location]

        return relevant
