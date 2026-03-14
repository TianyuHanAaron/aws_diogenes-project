import sys
from pathlib import Path
from unittest.mock import MagicMock


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from models import UserRequest
from services.digest_pipeline import DigestPipelineService


def test_collect_inputs_tolerates_seasonal_event_failures():
    news_tool = MagicMock()
    news_tool.run.return_value = []

    seasonal_events_tool = MagicMock()
    seasonal_events_tool.run.side_effect = RuntimeError("OPENAI_API_KEY is not set")

    photos_tool = MagicMock()
    photos_tool.run.return_value = []

    service = DigestPipelineService(
        news_tool=news_tool,
        seasonal_events_tool=seasonal_events_tool,
        photos_tool=photos_tool,
    )

    inputs = service.collect_inputs(
        UserRequest(location="sydney", hemisphere="southern", topic="astronomy")
    )

    assert inputs.news == []
    assert inputs.seasonal_events == []
    assert inputs.photos == []
