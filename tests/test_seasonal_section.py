import asyncio
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from models import SeasonalEventResult, UserRequest
from crews.seasonal_events.seasonal_events import (
    _clean_focus,
    _static_fallback_seasonal_entries,
)
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
        html = asyncio.run(service._render_seasonal_events(request, events))

    assert "Easter Monday" in html
    assert "upcoming two-week window" in html


def test_static_fallback_entries_keep_two_festivals_and_two_flowers():
    request = UserRequest(
        location="Sydney",
        hemisphere="southern",
        month="March",
        until="2026-03-15T10:00:00+11:00",
    )
    current_dt = datetime.fromisoformat(request.until)
    window_end = current_dt.replace(day=30)

    entries = _static_fallback_seasonal_entries(
        request.location,
        request.hemisphere,
        current_dt,
        window_end,
    )

    festival_entries = [entry for entry in entries if entry.get("badge") == "Festival"]
    flower_entries = [entry for entry in entries if entry.get("badge") != "Festival"]

    assert len(entries) == 4
    assert len(festival_entries) == 2
    assert len(flower_entries) == 2


def test_clean_focus_normalizes_short_focus_lines():
    assert _clean_focus("Focus: Japanese Culture-Hanami") == "Japanese Culture - Hanami"
    assert _clean_focus("") == "Seasonal Culture - Current Meaning"
