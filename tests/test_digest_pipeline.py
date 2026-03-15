import sys
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from models import UserRequest
from services.digest_pipeline import DigestPipelineService


def test_collect_inputs_tolerates_seasonal_event_failures():
    news_tool = MagicMock()
    news_tool.arun = AsyncMock(return_value=[])

    city_landmarks_tool = MagicMock()
    city_landmarks_tool.arun = AsyncMock(return_value={"landmarks": []})
    photos_tool = MagicMock()
    photos_tool.arun = AsyncMock(return_value=[])

    service = DigestPipelineService(
        news_tool=news_tool,
        city_landmarks_tool=city_landmarks_tool,
        photos_tool=photos_tool,
    )

    inputs = asyncio.run(
        service.collect_inputs(
            UserRequest(location="sydney", hemisphere="southern", topic="astronomy")
        )
    )

    assert inputs.news == []
    assert inputs.seasonal_events == []
    assert inputs.landmarks == []
    assert inputs.photos == []
