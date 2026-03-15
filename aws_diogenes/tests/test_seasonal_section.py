import sys
from pathlib import Path
from unittest.mock import patch


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from models import SeasonalEventResult, UserRequest
from services.digest_pipeline import DigestPipelineService


def test_render_seasonal_events_uses_dedicated_crew_output():
    service = DigestPipelineService()
    request = UserRequest(
        location="Sydney",
        hemisphere="southern",
        month="March",
        until="2026-03-15T10:00:00+11:00",
    )
    events = [SeasonalEventResult(query="placeholder", content=[{"markdown": "placeholder"}])]

    with patch(
        "services.digest_pipeline.generate_seasonal_section",
        return_value=(
            '<div class="event"><span class="badge">Seasonal</span>'
            "<strong>Easter Monday</strong><br>"
            "Easter Monday falls within the upcoming two-week window and is observed "
            "as a public holiday across Australia, New Zealand, and several European "
            "countries.</div>"
        ),
    ):
        html = service._render_seasonal_events(request, events)

    assert "Easter Monday" in html
    assert "upcoming two-week window" in html
