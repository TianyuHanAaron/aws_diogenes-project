import sys
import asyncio
from pathlib import Path
from unittest.mock import patch


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from models import CityLandmark, PhotoCandidate
from services.digest_pipeline import DigestPipelineService


def test_render_photos_uses_direct_agent_output():
    service = DigestPipelineService()
    photos = [
        PhotoCandidate(photo_id="p1", url="https://images.pexels.com/p1.jpg", location="Sydney", source="pexels", raw={}),
        PhotoCandidate(photo_id="p2", url="https://images.pexels.com/p2.jpg", location="Sydney", source="pexels", raw={}),
    ]

    with patch(
        "services.digest_pipeline.generate_photo_album",
        return_value=('<tr><td>photo one</td></tr><tr><td>photo two</td></tr>', ["p1", "p2"]),
    ):
        html, keys = asyncio.run(service._render_photos(photos, "Sydney"))

    assert "photo one" in html
    assert keys == ["p1", "p2"]


def test_render_world_glance_returns_button_rows_and_links():
    service = DigestPipelineService()
    landmarks = [
        CityLandmark(name="Sydney Harbour", image="", stream="https://example.com"),
    ]

    html, links = asyncio.run(service._render_live_city_landmarks(landmarks, "Sydney"))

    assert "Sydney Harbour" in html
    assert "https://example.com" in html
    assert links == ["https://example.com"]


def test_build_photo_inputs_skips_people_focused_images():
    service = DigestPipelineService()
    photos = [
        PhotoCandidate(
            photo_id="p1",
            url="https://images.pexels.com/p1.jpg",
            location="Sydney",
            source="pexels",
            raw={"alt": "Portrait of smiling woman in Sydney street market"},
        ),
        PhotoCandidate(
            photo_id="p2",
            url="https://images.pexels.com/p2.jpg",
            location="Sydney",
            source="pexels",
            raw={"alt": "Sydney waterfront at sunset with ferries"},
        ),
    ]

    payload = service._build_photo_inputs(photos)

    assert len(payload) == 1
    assert payload[0]["photo_key"] == "p2"
