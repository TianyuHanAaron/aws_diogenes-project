"""YAML-driven helpers for the news digest section."""

from __future__ import annotations

from html import unescape as html_unescape
from pathlib import Path
import re
from typing import Any

from crews.runtime_utils import (
    build_task_prompt,
    call_nova_text_async,
    extract_json,
    load_yaml_async,
)


CONFIG_DIR = Path(__file__).resolve().parent / "config"
PARSE_BATCH_SIZE = 8
EVENT_STAGE_LIMIT = 24


async def generate_news_digest(news_items, request) -> dict[str, list[dict]]:
    """Run the staged news prompts and return final channel sections."""
    print("News digest: parsing raw stories...")
    agents, tasks = await load_yaml_async(CONFIG_DIR / "agents.yaml"), await load_yaml_async(CONFIG_DIR / "tasks.yaml")
    values = {
        "location": request.location,
        "topic": request.topic,
        "interests": ", ".join(request.interests) if request.interests else request.topic,
    }
    serialized_news = _serialize_news_items(news_items)
    if not serialized_news:
        return {}
    source_lookup = {str(item["id"]): item for item in serialized_news}
    parse_payload = await _parse_news_batches(
        agents["news_parse_agent"],
        tasks["news_parse_task"],
        values,
        serialized_news,
    )
    print("News digest: combining stories into events...")
    event_candidates = _prioritize_parsed_items(parse_payload)
    event_payload = await _run_json_stage(
        agents["news_event_agent"],
        tasks["news_event_task"],
        values,
        {"parsed_news": event_candidates},
        max_tokens=4200,
    )
    print("News digest: ranking events...")
    rank_payload = await _run_json_stage(
        agents["news_rank_agent"],
        tasks["news_rank_task"],
        values,
        {"events": event_payload, "channels": request.channels},
        max_tokens=3200,
    )
    ranked_source_evidence = _build_ranked_source_evidence(rank_payload, source_lookup)
    print("News digest: rewriting event summaries...")
    digest_payload = await _run_json_stage(
        agents["news_digest_agent"],
        tasks["news_digest_task"],
        values,
        {"ranked_events": rank_payload, "ranked_source_evidence": ranked_source_evidence},
        max_tokens=5200,
    )
    print("News digest: validating channel fit...")
    validation_payload = await _run_json_stage(
        agents["news_validation_agent"],
        tasks["news_validation_task"],
        values,
        {"draft_news": digest_payload, "channels": request.channels, "ranked_source_evidence": ranked_source_evidence},
        max_tokens=5200,
    )
    print("News digest: formatting final sections...")
    final_payload = await _run_json_stage(
        agents["news_layout_agent"],
        tasks["news_layout_task"],
        values,
        {"validated_news": validation_payload, "channels": request.channels},
        max_tokens=5200,
    )
    print("News digest: running final review...")
    reviewed_payload = await _run_json_stage(
        agents["news_final_review_agent"],
        tasks["news_final_review_task"],
        values,
        {"layout_news": final_payload, "channels": request.channels, "ranked_source_evidence": ranked_source_evidence},
        max_tokens=5200,
    )
    publishable_payload = _first_non_empty_news_payload(
        request.channels,
        reviewed_payload,
        final_payload,
        validation_payload,
        digest_payload,
    )
    event_lookup = _merge_ranked_event_sources(_event_lookup(event_payload), rank_payload)
    normalized = _sanitize_news_sections(
        publishable_payload,
        request.channels,
        location=request.location,
        event_lookup=event_lookup,
        source_lookup=source_lookup,
    )
    normalized = _rebalance_news_sections(normalized, request.channels)
    request.channels = [channel for channel in request.channels if channel.lower() in normalized]
    print("News digest: done")
    return normalized


async def _run_json_stage(
    agent_config: dict,
    task_config: dict,
    values: dict,
    payloads: dict,
    *,
    max_tokens: int = 2600,
) -> dict | list:
    """Render one YAML-defined prompt stage and decode its JSON response."""
    prompt = build_task_prompt(agent_config, task_config, values, payloads)
    payload = extract_json(await call_nova_text_async(prompt, max_tokens=max_tokens))
    if isinstance(payload, (dict, list)):
        return payload
    return {} if "JSON object" in str(task_config.get("expected_output", "")) else []


async def _parse_news_batches(
    agent_config: dict,
    task_config: dict,
    values: dict,
    serialized_news: list[dict],
) -> list[dict]:
    """Parse raw news in smaller batches so one truncated response does not zero the whole digest."""
    combined: list[dict] = []
    for index, batch in enumerate(_chunked(serialized_news, PARSE_BATCH_SIZE), start=1):
        if len(serialized_news) > PARSE_BATCH_SIZE:
            print(f"News digest: parsing batch {index}...")
        payload = await _run_json_stage(
            agent_config,
            task_config,
            values,
            {"news": batch},
            max_tokens=3600,
        )
        if isinstance(payload, list):
            combined.extend(item for item in payload if isinstance(item, dict))
    return combined


def _sanitize_news_sections(
    payload: dict,
    channels: list[str],
    *,
    location: str,
    event_lookup: dict[str, dict[str, Any]],
    source_lookup: dict[str, dict[str, Any]],
) -> dict[str, list[dict]]:
    """Keep the agent output publishable while requiring source linkage."""
    selected_channels = [channel.lower() for channel in channels]
    normalized: dict[str, list[dict]] = {}
    for channel in selected_channels:
        items = payload.get(channel, [])
        if not isinstance(items, list):
            continue

        kept: list[dict] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            event_id = str(item.get("event_id", "") or f"{channel}-{len(kept) + 1}")
            event = event_lookup.get(event_id, {})
            source_ids = _valid_source_ids(item.get("source_ids"), event, source_lookup)
            summary = _clean_text(str(item.get("summary", "") or ""))
            summary = _trim_summary(summary)
            if not source_ids or not summary or _looks_like_json(summary):
                continue
            if _looks_like_marketing_copy(summary.lower()) or _contains_disallowed_news_phrasing(summary):
                continue
            if channel == "local" and not _is_local_event(source_ids, source_lookup, location):
                continue
            kept.append(
                {
                    "rank": len(kept) + 1,
                    "event_id": event_id,
                    "source_ids": source_ids,
                    "summary": summary,
                }
            )
            if len(kept) >= 10:
                break

        if kept:
            normalized[channel] = kept

    return normalized


def _rebalance_news_sections(payload: dict[str, list[dict]], channels: list[str]) -> dict[str, list[dict]]:
    """Apply the final slot allocation after the agent stages have finished."""
    selected = [str(channel).lower() for channel in channels]
    global_limit = 5
    other_selected_channels = [channel for channel in selected if channel != "global"]
    if "global" in selected and other_selected_channels:
        if all(not payload.get(channel) for channel in other_selected_channels):
            global_limit = 10

    balanced: dict[str, list[dict]] = {}
    for channel, items in payload.items():
        if not isinstance(items, list) or not items:
            continue
        limit = global_limit if channel == "global" else 5
        trimmed = []
        for index, item in enumerate(items[:limit], start=1):
            if not isinstance(item, dict):
                continue
            current = dict(item)
            current["rank"] = index
            trimmed.append(current)
        if trimmed:
            balanced[channel] = trimmed
    return balanced


def _first_non_empty_news_payload(channels: list[str], *payloads: dict | list) -> dict:
    """Prefer the latest non-empty agent stage, but recover if a review stage over-prunes."""
    selected = [str(channel).lower() for channel in channels]
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for channel in selected:
            items = payload.get(channel, [])
            if isinstance(items, list) and items:
                return payload
    return {}


def _prioritize_parsed_items(payload: list | dict) -> list[dict]:
    """Trim the event-stage input using the parser's own signal labels."""
    if not isinstance(payload, list):
        return []
    items = [item for item in payload if isinstance(item, dict)]

    def score(item: dict[str, Any]) -> tuple[int, int, int, int, str]:
        headline = 1 if item.get("headline_grade") else 0
        event_driven = 1 if item.get("event_driven") else 0
        quote_penalty = 0 if item.get("quote_driven") else 1
        fact_count = len(item.get("fact_points", []) or [])
        identifier = str(item.get("id", ""))
        return (headline, event_driven, quote_penalty, fact_count, identifier)

    prioritized = sorted(items, key=score, reverse=True)
    return prioritized[:EVENT_STAGE_LIMIT]


def _chunked(items: list[dict], size: int) -> list[list[dict]]:
    """Split a list into smaller slices for safer LLM stages."""
    return [items[index:index + size] for index in range(0, len(items), size)]


def _serialize_news_items(news_items) -> list[dict]:
    """Trim the raw news objects down to the fields the prompt stages need."""
    serialized = []
    for index, item in enumerate(news_items, start=1):
        title = _clean_text(item.title)
        summary = _clean_text(item.summary)
        body = _trim_body_text(_clean_text(getattr(item, "body", "")))
        if not title or not (body or summary or title):
            continue
        serialized.append(
            {
                "id": index,
                "title": title,
                "summary": summary,
                "body": body,
                "source": _clean_text(item.source),
                "published": item.published,
                "url": item.url,
            }
        )
    return serialized


def _build_ranked_source_evidence(rank_payload: dict | list, source_lookup: dict[str, dict[str, Any]]) -> dict[str, list[dict]]:
    """Pass only the evidence tied to ranked events into the later agent stages."""
    if not isinstance(rank_payload, dict):
        return {}

    evidence: dict[str, list[dict]] = {}
    for channel, items in rank_payload.items():
        if not isinstance(items, list):
            continue
        channel_evidence: list[dict] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            source_ids = [str(source_id).strip() for source_id in item.get("source_ids", []) if str(source_id).strip()]
            linked_sources = []
            for source_id in source_ids[:3]:
                source_item = source_lookup.get(source_id)
                if not source_item:
                    continue
                linked_sources.append(
                    {
                        "id": source_id,
                        "title": source_item.get("title", ""),
                        "summary": source_item.get("summary", ""),
                        "body": _trim_body_text(str(source_item.get("body", "") or "")),
                        "source": source_item.get("source", ""),
                        "published": source_item.get("published", ""),
                        "url": source_item.get("url", ""),
                    }
                )
            channel_evidence.append(
                {
                    "rank": item.get("rank"),
                    "event_id": item.get("event_id"),
                    "event_statement": item.get("event_statement", ""),
                    "source_ids": source_ids,
                    "sources": linked_sources,
                }
            )
        if channel_evidence:
            evidence[str(channel).lower()] = channel_evidence
    return evidence


def _event_lookup(payload: list | dict) -> dict[str, dict[str, Any]]:
    """Index event-stage output by event id for later grounding checks."""
    if not isinstance(payload, list):
        return {}

    indexed: dict[str, dict[str, Any]] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        event_id = str(item.get("event_id", "") or "").strip()
        if not event_id:
            continue
        indexed[event_id] = item
    return indexed


def _merge_ranked_event_sources(
    event_lookup: dict[str, dict[str, Any]],
    rank_payload: dict | list,
) -> dict[str, dict[str, Any]]:
    """Recover event provenance from the rank stage when later stages get lossy."""
    merged = dict(event_lookup)
    if not isinstance(rank_payload, dict):
        return merged

    for items in rank_payload.values():
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            event_id = str(item.get("event_id", "") or "").strip()
            if not event_id:
                continue
            current = dict(merged.get(event_id, {}))
            if not current.get("source_ids"):
                current["source_ids"] = item.get("source_ids", []) or []
            if not current.get("event_statement"):
                current["event_statement"] = item.get("event_statement", "") or ""
            merged[event_id] = current
    return merged


def _trim_summary(text: str) -> str:
    """Allow long paragraphs while still preventing runaway model output."""
    words = text.split()
    if len(words) <= 520:
        return text
    trimmed = " ".join(words[:520]).rstrip(" ,;:")
    if trimmed and trimmed[-1] not in ".!?":
        trimmed += "."
    return trimmed


def _trim_body_text(text: str) -> str:
    """Keep source body excerpts informative without blowing up prompt size."""
    words = text.split()
    if len(words) <= 220:
        return text
    trimmed = " ".join(words[:220]).rstrip(" ,;:")
    if trimmed and trimmed[-1] not in ".!?":
        trimmed += "."
    return trimmed


def _clean_text(text: str) -> str:
    """Strip HTML noise and normalize whitespace."""
    cleaned = html_unescape(str(text or ""))
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _valid_source_ids(source_ids_payload: Any, event: dict[str, Any], source_lookup: dict[str, dict[str, Any]]) -> list[str]:
    """Keep only source ids that point to actual fetched news items."""
    raw_source_ids = source_ids_payload if isinstance(source_ids_payload, list) else event.get("source_ids", [])
    valid: list[str] = []
    for source_id in raw_source_ids or []:
        normalized = str(source_id).strip()
        if normalized and normalized in source_lookup and normalized not in valid:
            valid.append(normalized)
    return valid


def _is_local_event(source_ids: list[str], source_lookup: dict[str, dict[str, Any]], location: str) -> bool:
    """Require local items to mention the user's city or immediate place terms."""
    keywords = _local_keywords(location)
    if not keywords:
        return False

    evidence_text = " ".join(
        _clean_text(
            " ".join(
                [
                    str(source_lookup.get(source_id, {}).get("title", "") or ""),
                    str(source_lookup.get(source_id, {}).get("summary", "") or ""),
                    str(source_lookup.get(source_id, {}).get("body", "") or ""),
                ]
            )
        ).lower()
        for source_id in source_ids
    )
    if not evidence_text:
        return False

    for keyword in keywords:
        if keyword in evidence_text:
            return True
    return False


def _local_keywords(location: str) -> list[str]:
    """Build strict place keywords from the user's location string."""
    primary = _clean_text((location or "").split(",")[0]).lower()
    if not primary:
        return []

    keywords = [primary]
    token_parts = [part for part in re.split(r"[\s/-]+", primary) if len(part) >= 4]
    for token in token_parts:
        if token not in keywords:
            keywords.append(token)
    return keywords


def _contains_disallowed_news_phrasing(text: str) -> bool:
    """Reject direct quotes and low-signal colloquial phrasing."""
    lowered = text.lower()
    patterns = [
        r"‘[^’]+’",
        r"'[^']+'",
        r"\"[^\"]+\"",
        r"\bwe were ready\b",
        r"\bsmoking something\b",
        r"\bshocked\b",
        r"\bnews quiz\b",
        r"\bto forget\b",
        r"\bwhat started with\b",
    ]
    return any(re.search(pattern, lowered) for pattern in patterns)


def _looks_like_marketing_copy(lowered: str) -> bool:
    """Filter out newsletter/promotional lines before they reach the digest."""
    patterns = [
        r"\bhello and welcome\b",
        r"\bif this was forwarded\b",
        r"\bsubscribe\b",
        r"\bnewsletter\b",
        r"\bcan i interest you\b",
        r"\blocal picks\b",
        r"\bspecial events\b",
        r"\btickets?\b",
    ]
    return any(re.search(pattern, lowered) for pattern in patterns)


def _looks_like_json(text: str) -> bool:
    """Catch malformed model output that still looks like serialized data."""
    lowered = text.lower()
    return "photo_key" in lowered or "image_url" in lowered or ("{" in text and "}" in text)
