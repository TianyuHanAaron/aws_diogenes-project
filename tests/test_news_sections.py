import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from models import NewsItem, UserRequest
from crews.news_digest.news_digest import (
    _best_available_news_payload,
    _merge_serialized_news,
    _needs_news_retry,
    _parse_news_batches,
    _query_specs_from_payload,
    _fallback_article_summary,
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

    assert "military deployment" in html
    assert "Middle East" in html
    assert "museum expansion" in html
    assert "arts district" in html
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
                    "Instagram will no longer support end-to-end encrypted direct messages starting May 8, "
                    "ending a privacy feature that Meta says was used by relatively few people inside the app. "
                    "The company confirmed the change in a statement to The Verge and said the option will be "
                    "removed from Instagram's direct-message product rather than expanded further. The decision "
                    "narrows the encrypted messaging tools available in the service and marks a retreat from an "
                    "earlier push to make stronger message privacy more visible across Meta's consumer apps."
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
            "summary": (
                "Instagram will no longer support end-to-end encrypted direct messages starting May 8, ending a "
                "privacy option that Meta said relatively few people used inside the app. The company confirmed "
                "the change in a statement and said the feature will be removed from Instagram's direct-message "
                "product rather than expanded as part of a broader encrypted messaging strategy."
            ),
            "body": (
                "Meta said the feature was used by relatively few people and confirmed the change in a statement "
                "to The Verge. The decision narrows the encrypted messaging tools available inside Instagram and "
                "marks a retreat from an earlier push to make stronger message privacy more visible across Meta's "
                "consumer apps."
            ),
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


def test_sanitize_news_sections_drops_too_short_summary():
    payload = {
        "global": [
            {
                "rank": 1,
                "event_id": "evt-short",
                "source_ids": ["1"],
                "summary": "The central bank held rates steady after its meeting and repeated its inflation warning.",
            }
        ]
    }

    normalized = _sanitize_news_sections(
        payload,
        ["global"],
        location="Sydney",
        event_lookup={"evt-short": {"event_id": "evt-short", "source_ids": ["1"]}},
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
                    "after a review of peak-hour congestion and commuter demand. The proposal adds more frequent "
                    "services on core CBD routes, changes stop spacing in the busiest corridor, and directs "
                    "transport planners to monitor crowding during the morning commute. Officials said the plan "
                    "is meant to improve reliability for Melbourne passengers who rely on the tram network each day."
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
                "body": (
                    "Melbourne transport officials outlined a new tram service plan for the CBD, saying the "
                    "changes would target peak-hour congestion, improve service reliability, and help regular "
                    "commuters move through the central city more efficiently."
                ),
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


def test_rebalance_news_sections_expands_global_to_reach_minimum_total():
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

    assert len(normalized["global"]) == 7
    assert len(normalized["interest"]) == 1
    assert sum(len(items) for items in normalized.values()) == 8


def test_rebalance_news_sections_keeps_default_limit_when_total_is_already_full():
    payload = {
        "global": [
            {"rank": 1, "event_id": f"evt-{index}", "source_ids": [str(index)], "summary": f"Summary {index}."}
            for index in range(1, 9)
        ],
        "investment": [
            {"rank": 1, "event_id": f"evt-invest-{index}", "source_ids": [str(index)], "summary": f"Investment {index}."}
            for index in range(1, 5)
        ],
    }

    normalized = _rebalance_news_sections(payload, ["global", "investment"])

    assert len(normalized["global"]) == 5
    assert len(normalized["investment"]) == 4


def test_rebalance_news_sections_prefers_multi_source_items_when_trimming():
    payload = {
        "global": [
            {"rank": 1, "event_id": "evt-1", "source_ids": ["1"], "summary": "Single source one."},
            {"rank": 2, "event_id": "evt-2", "source_ids": ["2"], "summary": "Single source two."},
            {"rank": 3, "event_id": "evt-3", "source_ids": ["3"], "summary": "Single source three."},
            {"rank": 4, "event_id": "evt-4", "source_ids": ["4"], "summary": "Single source four."},
            {"rank": 5, "event_id": "evt-5", "source_ids": ["5"], "summary": "Single source five."},
            {"rank": 6, "event_id": "evt-6", "source_ids": ["6", "7"], "summary": "Corroborated event."},
        ]
    }

    normalized = _rebalance_news_sections(payload, ["global"])

    event_ids = [item["event_id"] for item in normalized["global"]]
    assert "evt-6" in event_ids
    assert len(normalized["global"]) == 6
    assert normalized["global"][0]["event_id"] == "evt-6"


def test_best_available_news_payload_falls_back_to_validation_stage():
    payload = _best_available_news_payload(
        ["global", "interest"],
        {},
        {"global": []},
        {"global": [{"rank": 1, "summary": "Grounded summary.", "event_id": "evt-1", "source_ids": ["1"]}]},
    )

    assert "global" in payload
    assert payload["global"][0]["summary"] == "Grounded summary."


def test_best_available_news_payload_prefers_more_corroborated_stage():
    payload = _best_available_news_payload(
        ["global"],
        {
            "global": [
                {"rank": 1, "summary": "Single source summary one.", "event_id": "evt-1", "source_ids": ["1"]},
                {"rank": 2, "summary": "Single source summary two.", "event_id": "evt-2", "source_ids": ["2"]},
                {"rank": 3, "summary": "Single source summary three.", "event_id": "evt-3", "source_ids": ["3"]},
            ]
        },
        {
            "global": [
                {"rank": 1, "summary": "Corroborated summary one.", "event_id": "evt-a", "source_ids": ["1", "2"]},
                {"rank": 2, "summary": "Corroborated summary two.", "event_id": "evt-b", "source_ids": ["3", "4"]},
                {"rank": 3, "summary": "Corroborated summary three.", "event_id": "evt-c", "source_ids": ["5", "6"]},
            ]
        },
    )

    assert [item["event_id"] for item in payload["global"]] == ["evt-a", "evt-b", "evt-c"]


def test_fallback_article_summary_drops_provider_truncation_markers():
    summary = _fallback_article_summary(
        {
            "title": "Jeffrey Epstein saw promise in Bitcoin and its far-right supporters",
            "summary": (
                "The tranche of Jeffrey Epstein emails and files released on January 30th tie the infamous "
                "pedophile, sex trafficker, and influence peddler to elite figures across the tech industry."
            ),
            "body": (
                "Epstein's connections are intrig…. Jeffrey Epstein saw promise in Bitcoin and its far-right "
                "supporters Epstein may not have fully understood crypto, but he helped shape its culture "
                "anyway. by D… [+21731 chars]."
            ),
            "source": "Example",
            "url": "https://example.com/story",
        }
    )

    assert "[+21731 chars]" not in summary
    assert "by D" not in summary
    assert "intrig…" not in summary


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
    serialized_news = [{"id": index, "title": f"Title {index}"} for index in range(1, 19)]

    with patch(
        "crews.news_digest.news_digest.run_json_stage",
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


def test_query_specs_from_payload_dedupes_and_limits_queries():
    payload = {
        "queries": [
            {"query": "global market news", "channel": "investment"},
            {"query": "global market news", "channel": "investment"},
            {"query": "Sydney transport", "channel": "local"},
        ]
    }

    specs = _query_specs_from_payload(payload, 2)

    assert specs == [
        {"query": "global market news", "channel": "investment"},
        {"query": "Sydney transport", "channel": "local"},
    ]


def test_merge_serialized_news_reassigns_ids_after_deduping():
    merged = _merge_serialized_news(
        [
            {"id": 1, "title": "A", "summary": "x", "body": "", "source": "BBC", "url": "https://a"},
        ],
        [
            {"id": 99, "title": "A", "summary": "x", "body": "", "source": "BBC", "url": "https://a"},
            {"id": 100, "title": "B", "summary": "y", "body": "", "source": "Reuters", "url": "https://b"},
        ],
    )

    assert [item["id"] for item in merged] == [1, 2]
    assert [item["title"] for item in merged] == ["A", "B"]


def test_needs_news_retry_when_selected_channel_has_no_approved_evidence():
    needs_retry = _needs_news_retry(
        ["global", "investment"],
        {"global": [{"rank": 1}], "investment": [{"rank": 1}]},
        {
            "global": [{"approved": True}],
            "investment": [{"approved": False}],
        },
    )

    assert needs_retry is True
