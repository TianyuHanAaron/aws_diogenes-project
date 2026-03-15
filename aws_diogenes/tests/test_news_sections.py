import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from models import NewsItem, UserRequest
from crews.news_digest.news_digest import (
    _first_non_empty_news_payload,
    _parse_news_batches,
    _rebalance_news_sections,
    _sanitize_news_sections,
)
from services.digest_pipeline import DigestPipelineService


def test_render_news_sections_uses_agent_pipeline():
    service = DigestPipelineService()
    request = UserRequest(
        location="Sydney",
        channels=["global", "interest"],
        interests=["art"],
        since="2026-03-01T00:00:00+11:00",
        until="2026-03-15T12:00:00+11:00",
    )
    news = [
        NewsItem(title="Global item", summary="...", source="Example"),
        NewsItem(title="Interest item", summary="...", source="Example"),
    ]

    with patch(
        "services.digest_pipeline.generate_news_digest",
        return_value={
            "global": [
                {"rank": 1, "summary": "A new military deployment was announced for the Middle East."}
            ],
            "interest": [
                {"rank": 1, "summary": "A major museum expansion was approved for the city arts district."}
            ],
        },
    ):
        html = asyncio.run(service._render_news_sections(news, request))

    assert "1.</strong> A new military deployment was announced for the Middle East." in html
    assert "1.</strong> A major museum expansion was approved for the city arts district." in html
    assert html.index("Global") < html.index("Interest")


def test_render_news_sections_omits_empty_selected_channels():
    service = DigestPipelineService()
    request = UserRequest(
        location="Sydney",
        channels=["global", "local", "investment", "interest"],
        interests=["art"],
        since="2026-03-01T00:00:00+11:00",
        until="2026-03-15T12:00:00+11:00",
    )

    with patch(
        "services.digest_pipeline.generate_news_digest",
        return_value={
            "global": [{"rank": 1, "summary": "A long grounded global summary."}],
            "interest": [{"rank": 1, "summary": "A long grounded interest summary."}],
        },
    ):
        html = asyncio.run(service._render_news_sections([], request))

    assert "Global" in html
    assert "Interest" in html
    assert "Local" not in html
    assert "Investment" not in html


def test_sanitize_news_sections_keeps_agent_summary_when_source_ids_are_valid():
    payload = {
        "global": [
            {
                "rank": 1,
                "event_id": "evt-1",
                "source_ids": ["1"],
                "summary": (
                    "Instagram will no longer support end-to-end encrypted direct messages starting May 8. "
                    "Meta said the feature was used by very few people, according to a statement provided "
                    "to The Verge by spokesperson Dina El-Kassaby Luce. The change removes an option that "
                    "was introduced as part of the company's broader encrypted messaging push and narrows the "
                    "privacy features available inside Instagram's standalone DM product."
                ),
            }
        ]
    }
    event_lookup = {
        "evt-1": {
            "event_id": "evt-1",
            "source_ids": ["1"],
        }
    }
    source_lookup = {
        "1": {
            "id": 1,
            "title": "Instagram is getting rid of end-to-end encrypted DMs that very few people used",
            "summary": "Instagram will no longer support end-to-end encrypted messages starting May 8.",
            "source": "The Verge",
        }
    }

    normalized = _sanitize_news_sections(
        payload,
        ["global"],
        location="Sydney",
        event_lookup=event_lookup,
        source_lookup=source_lookup,
    )

    assert "global" in normalized
    summary = normalized["global"][0]["summary"]
    assert "Instagram will no longer support end-to-end encrypted direct messages" in summary
    assert normalized["global"][0]["source_ids"] == ["1"]


def test_sanitize_news_sections_drops_ungrounded_generic_event_when_no_sources_exist():
    payload = {
        "global": [
            {
                "rank": 1,
                "event_id": "evt-ghost",
                "summary": "A major economy has announced a significant regulatory change in the financial sector.",
            }
        ]
    }

    normalized = _sanitize_news_sections(
        payload,
        ["global"],
        location="Sydney",
        event_lookup={"evt-ghost": {"event_id": "evt-ghost", "source_ids": []}},
        source_lookup={},
    )

    assert normalized == {}


def test_sanitize_news_sections_drops_quote_driven_or_colloquial_copy():
    payload = {
        "global": [
            {
                "rank": 1,
                "event_id": "evt-quote",
                "source_ids": ["1"],
                "summary": "We were ready: attorneys general say they prepared a legal response before the ruling.",
            }
        ]
    }

    normalized = _sanitize_news_sections(
        payload,
        ["global"],
        location="Sydney",
        event_lookup={"evt-quote": {"event_id": "evt-quote", "source_ids": ["1"]}},
        source_lookup={"1": {"id": 1, "title": "Example", "summary": "Example", "source": "Example"}},
    )

    assert normalized == {}


def test_sanitize_news_sections_drops_non_local_city_from_local_channel():
    payload = {
        "local": [
            {
                "rank": 1,
                "event_id": "evt-remote",
                "source_ids": ["1"],
                "summary": (
                    "An explosion at a Jewish school in Amsterdam marks the second antisemitic attack "
                    "within two days and has intensified security concerns for Jewish communities."
                ),
            }
        ]
    }

    normalized = _sanitize_news_sections(
        payload,
        ["local"],
        location="Melbourne",
        event_lookup={"evt-remote": {"event_id": "evt-remote", "source_ids": ["1"]}},
        source_lookup={
            "1": {
                "id": 1,
                "title": "Explosion at Jewish school in Amsterdam marks second antisemitic attack",
                "summary": "The incident follows an earlier attack at a synagogue in Rotterdam.",
                "body": "Police in Amsterdam are investigating after an explosion at a Jewish school.",
                "source": "BBC News",
            }
        },
    )

    assert normalized == {}


def test_sanitize_news_sections_keeps_true_local_city_event():
    payload = {
        "local": [
            {
                "rank": 1,
                "event_id": "evt-melbourne",
                "source_ids": ["1"],
                "summary": (
                    "Melbourne officials announced a new tram service plan for the central business district "
                    "after a review of peak-hour congestion and commuter demand."
                ),
            }
        ]
    }

    normalized = _sanitize_news_sections(
        payload,
        ["local"],
        location="Melbourne",
        event_lookup={"evt-melbourne": {"event_id": "evt-melbourne", "source_ids": ["1"]}},
        source_lookup={
            "1": {
                "id": 1,
                "title": "Melbourne announces new tram service plan for CBD commuters",
                "summary": "The Victorian government says the plan will target peak-hour congestion.",
                "body": "Melbourne transport officials outlined a new tram service plan for the CBD.",
                "source": "ABC",
            }
        },
    )

    assert "local" in normalized


def test_rebalance_news_sections_expands_global_when_other_selected_channels_are_empty():
    payload = {
        "global": [
            {"rank": 1, "event_id": f"evt-{index}", "source_ids": [str(index)], "summary": f"Summary {index}."}
            for index in range(1, 12)
        ]
    }

    normalized = _rebalance_news_sections(payload, ["global", "local", "investment", "interest"])

    assert list(normalized) == ["global"]
    assert len(normalized["global"]) == 10
    assert [item["rank"] for item in normalized["global"]] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]


def test_rebalance_news_sections_keeps_default_limit_when_other_channel_has_news():
    payload = {
        "global": [
            {"rank": 1, "event_id": f"evt-{index}", "source_ids": [str(index)], "summary": f"Summary {index}."}
            for index in range(1, 9)
        ],
        "interest": [
            {"rank": 1, "event_id": "evt-interest", "source_ids": ["99"], "summary": "Interest summary."}
        ],
    }

    normalized = _rebalance_news_sections(payload, ["global", "interest"])

    assert len(normalized["global"]) == 5
    assert len(normalized["interest"]) == 1


def test_first_non_empty_news_payload_falls_back_to_validation_stage():
    payload = _first_non_empty_news_payload(
        ["global", "interest"],
        {},
        {"global": []},
        {"global": [{"rank": 1, "summary": "Grounded summary.", "event_id": "evt-1", "source_ids": ["1"]}]},
    )

    assert "global" in payload
    assert payload["global"][0]["summary"] == "Grounded summary."


def test_prepare_news_items_preserves_body_text():
    service = DigestPipelineService()
    items = [
        NewsItem(
            title="Interest rates held steady by central bank",
            summary="The policy board kept rates unchanged at its March meeting.",
            body="The central bank said inflation remains elevated and signaled a cautious path for future moves.",
            source="Example",
        )
    ]

    prepared = service._prepare_news_items(items)

    assert prepared[0].body == "The central bank said inflation remains elevated and signaled a cautious path for future moves."


def test_parse_news_batches_combines_multiple_llm_batches():
    serialized_news = [{"id": index, "title": f"Title {index}"} for index in range(1, 10)]

    with patch(
        "crews.news_digest.news_digest._run_json_stage",
        new=AsyncMock(side_effect=[
            [{"id": 1, "development": "First batch event"}],
            [{"id": 9, "development": "Second batch event"}],
        ]),
    ):
        payload = asyncio.run(
            _parse_news_batches(
                {"role": "parser"},
                {"description": "parse"},
                {},
                serialized_news,
            )
        )

    assert payload == [
        {"id": 1, "development": "First batch event"},
        {"id": 9, "development": "Second batch event"},
    ]
