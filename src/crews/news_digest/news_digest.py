"""Stage runner for the YAML-driven news digest workflow."""

from __future__ import annotations

import asyncio
from html import unescape as html_unescape
from pathlib import Path
import re
from typing import Any

from models import NewsItem
from crews.runtime_utils import (
    load_stage_configs,
    run_json_stage,
)
from tools.fetch_news_tool import FetchNewsTool


CONFIG_DIR = Path(__file__).resolve().parent / "config"
PARSE_BATCH_SIZE = 12
PARSE_BATCH_CONCURRENCY = 4
EVENT_STAGE_LIMIT = 40
MIN_NEWS_SUMMARY_WORDS = 60
DEFAULT_CHANNEL_ITEM_LIMIT = 5
MIN_TOTAL_NEWS_ITEMS = 8
MAX_GLOBAL_OVERFLOW_ITEMS = 10
MAX_NEWS_QUERY_COUNT = 5
MAX_NEWS_RETRY_QUERY_COUNT = 3
MAX_SERIALIZED_NEWS_ITEMS = 96
FINANCE_FALLBACK_PATTERNS = [
    re.compile(pattern, flags=re.IGNORECASE)
    for pattern in [
        r"\bmarkets?\b",
        r"\bstocks?\b",
        r"\bshares?\b",
        r"\bbonds?\b",
        r"\byields?\b",
        r"\btreasury\b",
        r"\bfederal reserve\b",
        r"\bcentral bank\b",
        r"\binflation\b",
        r"\bearnings\b",
        r"\brevenue\b",
        r"\btariffs?\b",
        r"\btrade\b",
        r"\boil prices?\b",
        r"\bgas prices?\b",
        r"\bcurrencies?\b",
        r"\bcommodities\b",
        r"\binvestment\b",
    ]
]
GLOBAL_FALLBACK_PATTERNS = [
    re.compile(pattern, flags=re.IGNORECASE)
    for pattern in [
        r"\bpresident\b",
        r"\bprime minister\b",
        r"\bparliament\b",
        r"\bcongress\b",
        r"\bsanctions?\b",
        r"\bceasefire\b",
        r"\bairstrikes?\b",
        r"\bmilitary\b",
        r"\bwar\b",
        r"\bdiplomatic\b",
        r"\bregulation\b",
        r"\belection\b",
        r"\bgovernment\b",
        r"\bwhite house\b",
        r"\bunited nations\b",
        r"\beuropean union\b",
        r"\bconflict\b",
    ]
]
REPUTABLE_NEWS_SOURCES = {"bbc news", "reuters", "guardian", "the new york times", "new york times"}
TRUNCATION_MARKER_PATTERN = re.compile(r"\[\+\d+\s+chars?\]", flags=re.IGNORECASE)
TRUNCATED_FRAGMENT_PATTERNS = [
    re.compile(r"\[\+\d+\s+chars?\]", flags=re.IGNORECASE),
    re.compile(r"\bby\s+[A-Z][A-Za-z .'-]{0,80}(?:\.\.\.|…)\.?\s*$"),
    re.compile(r"\b[A-Za-z][A-Za-z'’-]{3,}(?:\.\.\.|…)\.?\s*$"),
    re.compile(r"(?:\.\.\.|…)\.?\s*$"),
]
NewsSectionPayload = dict[str, list[dict[str, Any]]]


async def generate_news_digest(news_items, request) -> dict[str, list[dict]]:
    """Run the full news workflow from retrieval planning through final review."""
    agents, tasks = await load_stage_configs(CONFIG_DIR)
    values = {
        "location": request.location,
        "topic": request.topic,
        "interests": ", ".join(request.interests) if request.interests else request.topic,
    }
    serialized_news = _serialize_news_items(news_items)
    print("News digest: planning retrieval queries...")
    planned_query_payload = await run_json_stage(
        agents["news_query_planner_agent"],
        tasks["news_query_planner_task"],
        values,
        {"channels": request.channels, "seed_news": serialized_news[:10]},
        max_tokens=2200,
    )
    print("News digest: fetching planned source coverage...")
    planned_news = await _fetch_planned_news(_query_specs_from_payload(planned_query_payload, MAX_NEWS_QUERY_COUNT))
    serialized_news = _limit_serialized_news_pool(_merge_serialized_news(planned_news, serialized_news))
    if not serialized_news:
        return {}

    cycle = await _run_news_retrieval_cycle(agents, tasks, values, request.channels, serialized_news)
    if _needs_news_retry(request.channels, cycle["rank_payload"], cycle["evidence_payload"]):
        print("News digest: planning one retrieval retry...")
        retry_query_payload = await run_json_stage(
            agents["news_retry_agent"],
            tasks["news_retry_task"],
            values,
            {
                "channels": request.channels,
                "ranked_evidence": cycle["evidence_payload"],
            },
            max_tokens=2200,
        )
        print("News digest: fetching retry coverage...")
        retry_news = await _fetch_planned_news(_query_specs_from_payload(retry_query_payload, MAX_NEWS_RETRY_QUERY_COUNT))
        if retry_news:
            serialized_news = _limit_serialized_news_pool(_merge_serialized_news(retry_news, serialized_news))
            cycle = await _run_news_retrieval_cycle(agents, tasks, values, request.channels, serialized_news)

    source_lookup = cycle["source_lookup"]
    event_payload = cycle["event_payload"]
    rank_payload = cycle["rank_payload"]
    ranked_source_evidence = cycle["ranked_source_evidence"]
    evidence_payload = cycle["evidence_payload"]
    print("News digest: rewriting event summaries...")
    digest_payload = await run_json_stage(
        agents["news_digest_agent"],
        tasks["news_digest_task"],
        values,
        {
            "ranked_events": rank_payload,
            "ranked_source_evidence": ranked_source_evidence,
            "ranked_evidence": evidence_payload,
        },
        max_tokens=7600,
    )
    print("News digest: validating channel fit...")
    validation_payload = await run_json_stage(
        agents["news_validation_agent"],
        tasks["news_validation_task"],
        values,
        {
            "draft_news": digest_payload,
            "channels": request.channels,
            "ranked_source_evidence": ranked_source_evidence,
            "ranked_evidence": evidence_payload,
        },
        max_tokens=7600,
    )
    print("News digest: formatting final sections...")
    final_payload = await run_json_stage(
        agents["news_layout_agent"],
        tasks["news_layout_task"],
        values,
        {"validated_news": validation_payload, "channels": request.channels},
        max_tokens=7600,
    )
    print("News digest: running final review...")
    reviewed_payload = await run_json_stage(
        agents["news_final_review_agent"],
        tasks["news_final_review_task"],
        values,
        {
            "layout_news": final_payload,
            "channels": request.channels,
            "ranked_source_evidence": ranked_source_evidence,
            "ranked_evidence": evidence_payload,
        },
        max_tokens=7600,
    )
    publishable_payload = _best_available_news_payload(
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
    normalized = _supplement_news_sections(
        normalized,
        request.channels,
        evidence_payload=evidence_payload,
        rank_payload=rank_payload,
        event_lookup=event_lookup,
        source_lookup=source_lookup,
    )
    normalized = _supplement_from_source_pool(
        normalized,
        request.channels,
        serialized_news,
        location=request.location,
        interests=request.interests,
        topic=request.topic,
    )
    normalized = _rebalance_news_sections(normalized, request.channels)
    request.channels = [channel for channel in request.channels if channel.lower() in normalized]
    print("News digest: done")
    return normalized


async def _run_news_retrieval_cycle(
    agents: dict[str, dict],
    tasks: dict[str, dict],
    values: dict[str, Any],
    channels: list[str],
    serialized_news: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run one complete parse, rank, and evidence pass over the current news pool."""
    source_lookup = {str(item["id"]): item for item in serialized_news}
    print("News digest: parsing raw stories...")
    parse_payload = await _parse_news_batches(
        agents["news_parse_agent"],
        tasks["news_parse_task"],
        values,
        serialized_news,
    )
    print("News digest: combining stories into events...")
    event_candidates = _prioritize_parsed_items(parse_payload)
    event_payload = await run_json_stage(
        agents["news_event_agent"],
        tasks["news_event_task"],
        values,
        {"parsed_news": event_candidates},
        max_tokens=4200,
    )
    print("News digest: ranking events...")
    rank_payload = await run_json_stage(
        agents["news_rank_agent"],
        tasks["news_rank_task"],
        values,
        {"events": event_payload, "channels": channels},
        max_tokens=4200,
    )
    ranked_source_evidence = _build_ranked_source_evidence(rank_payload, source_lookup)
    print("News digest: extracting grounded evidence...")
    evidence_payload = await run_json_stage(
        agents["news_evidence_agent"],
        tasks["news_evidence_task"],
        values,
        {"channels": channels, "ranked_source_evidence": ranked_source_evidence},
        max_tokens=5200,
    )
    return {
        "source_lookup": source_lookup,
        "event_payload": event_payload,
        "rank_payload": rank_payload,
        "ranked_source_evidence": ranked_source_evidence,
        "evidence_payload": evidence_payload,
    }


async def _parse_news_batches(
    agent_config: dict,
    task_config: dict,
    values: dict,
    serialized_news: list[dict],
) -> list[dict]:
    """Parse raw news in smaller batches so one truncated response does not zero the digest."""
    combined: list[dict] = []
    batches = _chunked(serialized_news, PARSE_BATCH_SIZE)

    async def _parse_one(index: int, batch: list[dict]) -> tuple[int, list[dict]]:
        total = len(batches)
        if total > 1 and (index == 1 or index == total or index % 5 == 0):
            print(f"News digest: parsing batch {index}/{total}...")
        payload = await run_json_stage(
            agent_config,
            task_config,
            values,
            {"news": batch},
            max_tokens=3600,
        )
        if isinstance(payload, list):
            return index, [item for item in payload if isinstance(item, dict)]
        return index, []

    if len(batches) <= PARSE_BATCH_CONCURRENCY:
        results = [await _parse_one(index, batch) for index, batch in enumerate(batches, start=1)]
    else:
        semaphore = asyncio.Semaphore(PARSE_BATCH_CONCURRENCY)

        async def _guarded_parse(index: int, batch: list[dict]) -> tuple[int, list[dict]]:
            async with semaphore:
                return await _parse_one(index, batch)

        results = await asyncio.gather(
            *[_guarded_parse(index, batch) for index, batch in enumerate(batches, start=1)]
        )

    for _, items in sorted(results, key=lambda item: item[0]):
        combined.extend(items)
    return combined


def _sanitize_news_sections(
    payload: dict,
    channels: list[str],
    *,
    location: str,
    event_lookup: dict[str, dict[str, Any]],
    source_lookup: dict[str, dict[str, Any]],
) -> NewsSectionPayload:
    """Keep only grounded, channel-correct summaries from the later agent stages."""
    normalized: NewsSectionPayload = {}
    for channel in _selected_channel_ids(channels):
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
            grounded_summary = _grounded_summary_from_sources(
                item.get("event_statement", "") or event.get("event_statement", ""),
                source_ids,
                source_lookup,
            )
            summary = _trim_summary(summary)
            if grounded_summary and not _summary_is_grounded(summary, grounded_summary):
                summary = grounded_summary
            if not source_ids or not summary or _looks_like_json(summary):
                continue
            if not _meets_minimum_summary_length(summary):
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


def _supplement_news_sections(
    payload: NewsSectionPayload,
    channels: list[str],
    *,
    evidence_payload: dict | list,
    rank_payload: dict | list,
    event_lookup: dict[str, dict[str, Any]],
    source_lookup: dict[str, dict[str, Any]],
) -> NewsSectionPayload:
    """Backfill thin channels from ranked evidence before falling back to raw articles.

    This stage is still deterministic, but the rules are easier to follow if we
    treat them as:
    1. start from the already-approved agent output
    2. fill each selected channel up to its normal limit from ranked evidence
    3. if the digest is still under the minimum total, let global absorb the gap
    """
    supplemented = _normalized_section_payload(payload)
    selected = _selected_channel_ids(channels)
    used_event_ids = _collect_used_event_ids(supplemented)
    channel_limits = _build_channel_item_limits(selected, supplemented)

    for channel in selected:
        _extend_channel_from_ranked_candidates(
            supplemented=supplemented,
            channel=channel,
            candidates=_candidate_news_items_for_channel(channel, evidence_payload, rank_payload),
            channel_limit=channel_limits.get(channel, DEFAULT_CHANNEL_ITEM_LIMIT),
            used_event_ids=used_event_ids,
            event_lookup=event_lookup,
            source_lookup=source_lookup,
        )

    _extend_global_to_minimum_total_from_ranked_candidates(
        supplemented=supplemented,
        selected=selected,
        global_candidates=_candidate_news_items_for_channel("global", evidence_payload, rank_payload),
        used_event_ids=used_event_ids,
        event_lookup=event_lookup,
        source_lookup=source_lookup,
    )
    return _drop_empty_channels(supplemented)


def _supplement_from_source_pool(
    payload: NewsSectionPayload,
    channels: list[str],
    serialized_news: list[dict[str, Any]],
    *,
    location: str,
    interests: list[str],
    topic: str,
) -> NewsSectionPayload:
    """Backfill factual news directly from fetched articles when agent stages underfill.

    This is the last fallback. We keep it readable by separating:
    - channel selection
    - already-used source tracking
    - per-channel filling
    - global overflow when the digest is still below the minimum total
    """
    supplemented = _normalized_section_payload(payload)
    selected = _selected_channel_ids(channels)
    if not selected:
        return supplemented

    used_source_ids = _collect_used_source_ids(supplemented)
    source_candidates = _build_source_fallback_candidates(serialized_news, selected, location, interests, topic)
    channel_limits = _build_channel_item_limits(selected, supplemented)

    for channel in selected:
        supplemented.setdefault(channel, [])
        limit = channel_limits.get(channel, DEFAULT_CHANNEL_ITEM_LIMIT)
        for candidate in source_candidates:
            if len(supplemented[channel]) >= limit:
                break
            if candidate["channel"] != channel:
                continue
            source_id = candidate["source_id"]
            if source_id in used_source_ids:
                continue
            supplemented[channel].append(
                {
                    "rank": len(supplemented[channel]) + 1,
                    "event_id": f"raw-{channel}-{source_id}",
                    "source_ids": [source_id],
                    "summary": candidate["summary"],
                }
            )
            used_source_ids.add(source_id)

    if _total_news_items(supplemented) < MIN_TOTAL_NEWS_ITEMS and "global" in selected:
        supplemented.setdefault("global", [])
        for candidate in source_candidates:
            if candidate["channel"] not in {"global", "investment", "interest"}:
                continue
            source_id = candidate["source_id"]
            if source_id in used_source_ids:
                continue
            supplemented["global"].append(
                {
                    "rank": len(supplemented["global"]) + 1,
                    "event_id": f"raw-global-{source_id}",
                    "source_ids": [source_id],
                    "summary": candidate["summary"],
                }
            )
            used_source_ids.add(source_id)
            if (
                len(supplemented["global"]) >= MAX_GLOBAL_OVERFLOW_ITEMS
                or _total_news_items(supplemented) >= MIN_TOTAL_NEWS_ITEMS
            ):
                break

    return _drop_empty_channels(supplemented)


def _rebalance_news_sections(payload: NewsSectionPayload, channels: list[str]) -> NewsSectionPayload:
    """Apply the final channel caps in one easy-to-read pass.

    The end state should follow three rules:
    - normal channels cap at five items
    - global may expand when other selected channels are empty or thin
    - when trimming, corroborated events should survive before weaker ones
    """
    selected = _selected_channel_ids(channels)
    channel_limits = _build_channel_item_limits(selected, payload)
    balanced: NewsSectionPayload = {}
    for channel, items in payload.items():
        if not isinstance(items, list) or not items:
            continue
        limit = channel_limits.get(channel, DEFAULT_CHANNEL_ITEM_LIMIT)
        ordered_items = sorted(
            [item for item in items if isinstance(item, dict)],
            key=_final_news_item_priority,
        )
        trimmed = []
        for index, item in enumerate(ordered_items[:limit], start=1):
            current = dict(item)
            current["rank"] = index
            trimmed.append(current)
        if trimmed:
            balanced[channel] = trimmed
    return balanced


def _best_available_news_payload(channels: list[str], *payloads: dict | list) -> dict:
    """Recover underfilled channels by choosing the strongest stage per channel.

    When multiple late-stage payloads disagree, we prefer the one with:
    - more linked sources across the kept items
    - more multi-source events
    - then more items
    - then more written detail
    """
    selected = _selected_channel_ids(channels)
    best_payload: dict[str, list[dict[str, Any]]] = {}
    for channel in selected:
        best_items: list[dict[str, Any]] = []
        best_score: tuple[int, int, int, int] = (-1, -1, -1, -1)
        for payload in payloads:
            if not isinstance(payload, dict):
                continue
            items = payload.get(channel, [])
            if not isinstance(items, list):
                continue
            valid_items = [item for item in items if isinstance(item, dict)]
            score = _channel_payload_score(valid_items)
            if score > best_score:
                best_items = valid_items
                best_score = score
        if best_items:
            best_payload[channel] = best_items
    return best_payload


def _selected_channel_ids(channels: list[str]) -> list[str]:
    """Normalize user-selected channel ids once so the rest of the file can reuse them."""
    return [str(channel).lower() for channel in channels]


def _normalized_section_payload(payload: NewsSectionPayload) -> NewsSectionPayload:
    """Copy only the populated dict-based items from a section payload."""
    return {
        str(channel).lower(): [dict(item) for item in items if isinstance(item, dict)]
        for channel, items in payload.items()
        if isinstance(items, list) and items
    }


def _drop_empty_channels(payload: NewsSectionPayload) -> NewsSectionPayload:
    """Return only channels that still have at least one kept item."""
    return {channel: items for channel, items in payload.items() if items}


def _collect_used_event_ids(payload: NewsSectionPayload) -> set[str]:
    """Track which event ids are already represented in the digest."""
    return {
        str(item.get("event_id", "")).strip()
        for items in payload.values()
        for item in items
        if str(item.get("event_id", "")).strip()
    }


def _collect_used_source_ids(payload: NewsSectionPayload) -> set[str]:
    """Track which raw article ids have already been consumed by the digest."""
    return {
        str(source_id).strip()
        for items in payload.values()
        for item in items
        for source_id in item.get("source_ids", [])
        if str(source_id).strip()
    }


def _build_channel_item_limits(selected: list[str], payload: NewsSectionPayload) -> dict[str, int]:
    """Decide the target item limit for each selected channel.

    The logic is intentionally explicit:
    - non-global channels always use the default cap
    - if global is the only surviving selected channel, allow up to ten items
    - otherwise let global expand only enough to help reach the minimum total
    """
    limits = {channel: DEFAULT_CHANNEL_ITEM_LIMIT for channel in selected}
    if "global" not in selected:
        return limits

    non_global_selected = [channel for channel in selected if channel != "global"]
    if non_global_selected and all(not payload.get(channel) for channel in non_global_selected):
        limits["global"] = MAX_GLOBAL_OVERFLOW_ITEMS
        return limits

    non_global_item_count = sum(
        len(items[:DEFAULT_CHANNEL_ITEM_LIMIT])
        for channel, items in payload.items()
        if channel != "global" and isinstance(items, list)
    )
    limits["global"] = min(
        MAX_GLOBAL_OVERFLOW_ITEMS,
        max(DEFAULT_CHANNEL_ITEM_LIMIT, MIN_TOTAL_NEWS_ITEMS - non_global_item_count),
    )
    return limits


def _extend_channel_from_ranked_candidates(
    *,
    supplemented: NewsSectionPayload,
    channel: str,
    candidates: list[dict[str, Any]],
    channel_limit: int,
    used_event_ids: set[str],
    event_lookup: dict[str, dict[str, Any]],
    source_lookup: dict[str, dict[str, Any]],
) -> None:
    """Append grounded ranked candidates until one channel reaches its limit."""
    supplemented.setdefault(channel, [])
    for candidate in candidates:
        if len(supplemented[channel]) >= channel_limit:
            break
        appended = _append_ranked_candidate(
            destination=supplemented[channel],
            candidate=candidate,
            used_event_ids=used_event_ids,
            event_lookup=event_lookup,
            source_lookup=source_lookup,
        )
        if appended:
            used_event_ids.add(appended)


def _extend_global_to_minimum_total_from_ranked_candidates(
    *,
    supplemented: NewsSectionPayload,
    selected: list[str],
    global_candidates: list[dict[str, Any]],
    used_event_ids: set[str],
    event_lookup: dict[str, dict[str, Any]],
    source_lookup: dict[str, dict[str, Any]],
) -> None:
    """Let global absorb the remaining factual slots when the digest is underfilled."""
    if "global" not in selected or _total_news_items(supplemented) >= MIN_TOTAL_NEWS_ITEMS:
        return

    supplemented.setdefault("global", [])
    for candidate in global_candidates:
        if len(supplemented["global"]) >= MAX_GLOBAL_OVERFLOW_ITEMS:
            break
        if _total_news_items(supplemented) >= MIN_TOTAL_NEWS_ITEMS:
            break
        appended = _append_ranked_candidate(
            destination=supplemented["global"],
            candidate=candidate,
            used_event_ids=used_event_ids,
            event_lookup=event_lookup,
            source_lookup=source_lookup,
        )
        if appended:
            used_event_ids.add(appended)


def _append_ranked_candidate(
    *,
    destination: list[dict[str, Any]],
    candidate: dict[str, Any],
    used_event_ids: set[str],
    event_lookup: dict[str, dict[str, Any]],
    source_lookup: dict[str, dict[str, Any]],
) -> str:
    """Try to convert one ranked evidence candidate into a publishable item.

    Returns the appended event id on success, otherwise an empty string.
    """
    event_id = str(candidate.get("event_id", "") or "").strip()
    if not event_id or event_id in used_event_ids:
        return ""

    event = event_lookup.get(event_id, {})
    source_ids = _valid_source_ids(candidate.get("source_ids"), event, source_lookup)
    if not source_ids:
        return ""

    summary = _grounded_summary_from_sources(
        candidate.get("fact_brief", "") or candidate.get("event_statement", "") or event.get("event_statement", ""),
        source_ids,
        source_lookup,
    )
    if not _meets_minimum_summary_length(summary):
        return ""

    destination.append(
        {
            "rank": len(destination) + 1,
            "event_id": event_id,
            "source_ids": source_ids,
            "summary": summary,
        }
    )
    return event_id


def _total_news_items(payload: NewsSectionPayload) -> int:
    """Count how many news items currently survive across all channels."""
    return sum(len(items) for items in payload.values())


def _build_source_fallback_candidates(
    serialized_news: list[dict[str, Any]],
    selected_channels: list[str],
    location: str,
    interests: list[str],
    topic: str,
) -> list[dict[str, Any]]:
    """Convert fetched articles into channel-tagged factual fallback candidates."""
    candidates: list[dict[str, Any]] = []
    for item in serialized_news:
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("id", "")).strip()
        if not source_id:
            continue
        summary = _fallback_article_summary(item)
        if not _meets_minimum_summary_length(summary):
            continue
        if _looks_like_marketing_copy(summary.lower()) or _contains_disallowed_news_phrasing(summary):
            continue
        channel = _classify_source_fallback_channel(item, selected_channels, location, interests, topic)
        if not channel:
            continue
        candidates.append(
            {
                "source_id": source_id,
                "channel": channel,
                "summary": summary,
                "score": _source_candidate_score(item, channel, location, interests, topic),
            }
        )
    return sorted(candidates, key=lambda item: item["score"], reverse=True)


def _candidate_news_items_for_channel(channel: str, evidence_payload: dict | list, rank_payload: dict | list) -> list[dict[str, Any]]:
    """Collect unique ranked candidates for one channel, preferring approved evidence."""
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for payload in (evidence_payload, rank_payload):
        if not isinstance(payload, dict):
            continue
        items = payload.get(channel, [])
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            if payload is evidence_payload and item.get("approved") is False:
                continue
            event_id = str(item.get("event_id", "") or "").strip()
            if not event_id or event_id in seen:
                continue
            seen.add(event_id)
            candidates.append(item)
    return sorted(candidates, key=_candidate_news_item_priority)


def _classify_source_fallback_channel(
    item: dict[str, Any],
    selected_channels: list[str],
    location: str,
    interests: list[str],
    topic: str,
) -> str:
    """Pick the most plausible digest channel for one fetched article.

    The fallback classifier uses a clear priority order:
    1. local wins only when the article explicitly mentions the user's place
    2. investment wins when finance signals clearly outweigh global signals
    3. interest wins when the text is more about the user's interest terms
    4. otherwise global acts as the default hard-news bucket
    """
    text = _article_text_for_heuristics(item)
    local_keywords = _local_keywords(location)
    interest_terms = _interest_terms(interests, topic)

    local_match = "local" in selected_channels and any(keyword in text for keyword in local_keywords)
    finance_score = sum(1 for pattern in FINANCE_FALLBACK_PATTERNS if pattern.search(text))
    global_score = sum(1 for pattern in GLOBAL_FALLBACK_PATTERNS if pattern.search(text))
    interest_score = sum(1 for term in interest_terms if term and term in text)

    if local_match:
        return "local"
    if "investment" in selected_channels and finance_score >= max(2, global_score):
        return "investment"
    if "interest" in selected_channels and interest_score > max(finance_score, global_score):
        return "interest"
    if "global" in selected_channels:
        return "global"
    if "investment" in selected_channels and finance_score:
        return "investment"
    if "interest" in selected_channels and interest_score:
        return "interest"
    return selected_channels[0] if selected_channels else ""


def _source_candidate_score(
    item: dict[str, Any],
    channel: str,
    location: str,
    interests: list[str],
    topic: str,
) -> int:
    """Score fallback source candidates so stronger factual items fill first.

    The score is intentionally readable:
    - start with body/detail length
    - reward reputable sources
    - then add channel-specific keyword evidence
    """
    text = _article_text_for_heuristics(item)
    source_name = _clean_text(item.get("source", "")).lower()
    score = len(_clean_text(item.get("body", "")).split()) // 20
    if source_name in REPUTABLE_NEWS_SOURCES:
        score += 2
    if channel == "investment":
        score += sum(1 for pattern in FINANCE_FALLBACK_PATTERNS if pattern.search(text))
    elif channel == "global":
        score += sum(1 for pattern in GLOBAL_FALLBACK_PATTERNS if pattern.search(text))
    elif channel == "local":
        score += sum(1 for keyword in _local_keywords(location) if keyword in text)
    else:
        terms = _interest_terms(interests, topic)
        score += sum(1 for term in terms if term and term in text)
    return score


def _article_text_for_heuristics(item: dict[str, Any]) -> str:
    """Join the source title, summary, and body into one lowercase text block."""
    return " ".join(
        [
            _clean_text(item.get("title", "")),
            _clean_text(item.get("summary", "")),
            _clean_text(item.get("body", "")),
        ]
    ).lower()


def _interest_terms(interests: list[str], topic: str) -> list[str]:
    """Build the normalized set of interest terms used by heuristic classifiers."""
    terms = [term.lower() for term in interests if term.strip()]
    if topic and topic.lower() not in terms:
        terms.append(topic.lower())
    return terms


def _channel_payload_score(items: list[dict[str, Any]]) -> tuple[int, int, int, int]:
    """Score one channel payload so richer corroborated stages beat thinner ones."""
    if not items:
        return (-1, -1, -1, -1)
    total_sources = sum(min(3, _source_count(item)) for item in items)
    multi_source_items = sum(1 for item in items if _source_count(item) >= 2)
    item_count = len(items)
    total_words = sum(len(_clean_text(item.get("summary", "")).split()) for item in items)
    return (total_sources, multi_source_items, item_count, total_words)


def _candidate_news_item_priority(item: dict[str, Any]) -> tuple[int, int, int, int]:
    """Prefer corroborated approved evidence before weaker single-source candidates."""
    source_count = _source_count(item)
    approved = 1 if item.get("approved") else 0
    confidence = _confidence_score(item.get("confidence"))
    rank = int(item.get("rank", 9999) or 9999)
    return (-approved, -min(source_count, 3), -confidence, rank)


def _final_news_item_priority(item: dict[str, Any]) -> tuple[int, int, int, int]:
    """Prefer multi-source stories when trimming to the final per-channel slot limit."""
    source_count = _source_count(item)
    rank = int(item.get("rank", 9999) or 9999)
    summary_words = len(_clean_text(item.get("summary", "")).split())
    return (-min(source_count, 3), rank, -summary_words, str(item.get("event_id", "")))


def _source_count(item: dict[str, Any]) -> int:
    """Count distinct linked sources on a news item or evidence bundle."""
    source_ids = item.get("source_ids", [])
    if not isinstance(source_ids, list):
        return 0
    return len({str(source_id).strip() for source_id in source_ids if str(source_id).strip()})


def _confidence_score(value: Any) -> int:
    """Convert evidence confidence labels into a simple sortable score."""
    label = _clean_text(value).lower()
    return {"high": 3, "medium": 2, "low": 1}.get(label, 0)


def _query_specs_from_payload(payload: dict | list, limit: int) -> list[dict[str, str]]:
    """Normalize a query-planner payload into simple query specs."""
    if isinstance(payload, dict):
        raw_queries = payload.get("queries", [])
    elif isinstance(payload, list):
        raw_queries = payload
    else:
        raw_queries = []

    query_specs: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in raw_queries:
        if isinstance(item, dict):
            query = _clean_text(item.get("query", ""))
            channel = _clean_text(item.get("channel", item.get("entry_type", ""))).lower()
        else:
            query = _clean_text(item)
            channel = ""
        if not query:
            continue
        key = (query.lower(), channel)
        if key in seen:
            continue
        seen.add(key)
        query_specs.append({"query": query, "channel": channel})
        if len(query_specs) >= limit:
            break
    return query_specs


async def _fetch_planned_news(query_specs: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Fetch extra news coverage for the Nova-planned retrieval queries."""
    queries = [item["query"] for item in query_specs if item.get("query")]
    if not queries:
        return []

    tool = FetchNewsTool()
    try:
        raw_items = await tool.arun_queries(queries)
    except Exception:
        return []
    return _serialize_news_items([NewsItem.from_raw(item) for item in raw_items])


def _merge_serialized_news(*batches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge serialized news batches while preserving order and uniqueness."""
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for batch in batches:
        for item in batch:
            if not isinstance(item, dict):
                continue
            key = (
                _clean_text(item.get("url", "")).lower(),
                _clean_text(item.get("title", "")).lower(),
                _clean_text(item.get("source", "")).lower(),
            )
            if not any(key):
                continue
            if key in seen:
                continue
            seen.add(key)
            merged.append(dict(item))

    for index, item in enumerate(merged, start=1):
        item["id"] = index
    return merged


def _limit_serialized_news_pool(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cap the parse pool so retrieval expansion does not explode parse time."""
    limited = list(items[:MAX_SERIALIZED_NEWS_ITEMS])
    for index, item in enumerate(limited, start=1):
        item["id"] = index
    return limited


def _needs_news_retry(channels: list[str], rank_payload: dict | list, evidence_payload: dict | list) -> bool:
    """Decide whether the first retrieval pass left too many evidence gaps."""
    if not channels:
        return False
    approved_total = _count_approved_news_items(evidence_payload)
    if approved_total < MIN_TOTAL_NEWS_ITEMS:
        return True
    return False


def _count_news_items(payload: dict | list) -> int:
    """Count list items across a channel-keyed payload."""
    if not isinstance(payload, dict):
        return 0
    total = 0
    for items in payload.values():
        if isinstance(items, list):
            total += len(items)
    return total


def _count_approved_news_items(payload: dict | list) -> int:
    """Count evidence items that survived the approval check."""
    if not isinstance(payload, dict):
        return 0
    total = 0
    for items in payload.values():
        if not isinstance(items, list):
            continue
        total += sum(1 for item in items if isinstance(item, dict) and item.get("approved"))
    return total


def _prioritize_parsed_items(payload: list | dict) -> list[dict]:
    """Trim the event-stage input using the parser's own signal labels.

    Earlier parse items get promoted when they:
    - look headline-grade
    - describe a real event instead of quote-driven commentary
    - carry more factual bullets for the event stage to merge later
    """
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


def _meets_minimum_summary_length(text: str) -> bool:
    """Reject very short summaries so the digest keeps full, readable items."""
    return len(text.split()) >= MIN_NEWS_SUMMARY_WORDS


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


def _fallback_article_summary(item: dict[str, Any]) -> str:
    """Build a factual paragraph directly from one fetched article record."""
    parts: list[str] = []

    def _append(sentence: str) -> None:
        cleaned = _clean_text(sentence)
        if not cleaned:
            return
        if _duplicates_existing_sentence(cleaned, parts):
            return
        if cleaned[-1] not in ".!?":
            cleaned += "."
        if cleaned not in parts:
            parts.append(cleaned)

    title = _clean_text(item.get("title", ""))
    if title:
        _append(title)
    for field in ("summary", "body"):
        for sentence in _split_source_sentences(str(item.get(field, "") or "")):
            _append(sentence)
            if len(" ".join(parts).split()) >= max(MIN_NEWS_SUMMARY_WORDS, 90):
                return _trim_summary(" ".join(parts))
    return _trim_summary(" ".join(parts))


def _grounded_summary_from_sources(
    event_statement: str,
    source_ids: list[str],
    source_lookup: dict[str, dict[str, Any]],
) -> str:
    """Build a factual digest paragraph directly from the linked source coverage."""
    sentences: list[str] = []
    seen: set[str] = set()

    def _push(sentence: str) -> None:
        cleaned = _clean_text(sentence)
        if not cleaned:
            return
        if _duplicates_existing_sentence(cleaned, sentences):
            return
        normalized = cleaned.lower()
        if normalized in seen:
            return
        if _looks_like_marketing_copy(normalized) or _contains_disallowed_news_phrasing(cleaned):
            return
        if len(cleaned.split()) < 7:
            return
        if cleaned[-1] not in ".!?":
            cleaned += "."
        seen.add(normalized)
        sentences.append(cleaned)

    _push(event_statement)
    for source_id in source_ids[:3]:
        source = source_lookup.get(source_id, {})
        for field in ("summary", "body", "title"):
            for sentence in _split_source_sentences(str(source.get(field, "") or "")):
                _push(sentence)
                if len(" ".join(sentences).split()) >= max(MIN_NEWS_SUMMARY_WORDS, 120):
                    return " ".join(sentences)
    return " ".join(sentences)


def _split_source_sentences(text: str) -> list[str]:
    """Break raw source text into usable factual sentences."""
    cleaned = _clean_text(text)
    if not cleaned:
        return []
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    if len(parts) == 1:
        if _looks_truncated_source_fragment(cleaned):
            return []
        words = cleaned.split()
        return [" ".join(words[:32])] if words else []
    return [part for part in parts if part and not _looks_truncated_source_fragment(part)]


def _summary_is_grounded(summary: str, grounded_summary: str) -> bool:
    """Check whether the model summary overlaps enough with source-grounded wording."""
    if not summary or not grounded_summary:
        return False
    summary_tokens = _significant_tokens(summary)
    grounded_tokens = _significant_tokens(grounded_summary)
    if not summary_tokens or not grounded_tokens:
        return False
    overlap = len(summary_tokens & grounded_tokens)
    return overlap >= min(8, max(4, len(summary_tokens) // 6))


def _significant_tokens(text: str) -> set[str]:
    """Extract content-bearing tokens for lightweight grounding checks."""
    stopwords = {
        "about", "after", "again", "among", "being", "between", "could", "because",
        "during", "their", "there", "these", "those", "which", "while", "would",
        "where", "under", "other", "still", "through", "against", "across", "around",
        "people", "public", "global", "major", "market", "markets", "world", "event",
    }
    return {
        token
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9'-]+", text.lower())
        if len(token) >= 5 and token not in stopwords
    }


def _clean_text(text: str) -> str:
    """Strip HTML noise and normalize whitespace."""
    cleaned = html_unescape(str(text or ""))
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = TRUNCATION_MARKER_PATTERN.sub(" ", cleaned)
    cleaned = re.sub(r"\s+by\s+[A-Z][A-Za-z .'-]{0,80}(?:\.\.\.|…)\.?(?=\s|$)", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = _remove_truncated_sentences(cleaned)
    if not re.search(r"[A-Za-z0-9]", cleaned):
        return ""
    return cleaned


def _remove_truncated_sentences(text: str) -> str:
    """Drop provider snippets that end in truncation markers instead of full sentences."""
    if not text:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", text)
    if len(parts) == 1:
        return "" if _looks_truncated_source_fragment(text) else text
    kept = [part for part in parts if part and not _looks_truncated_source_fragment(part)]
    return " ".join(kept).strip()


def _looks_truncated_source_fragment(text: str) -> bool:
    """Detect provider snippets that were cut off mid-story."""
    cleaned = str(text or "").strip()
    if not cleaned:
        return False
    return any(pattern.search(cleaned) for pattern in TRUNCATED_FRAGMENT_PATTERNS)


def _duplicates_existing_sentence(candidate: str, existing_sentences: list[str]) -> bool:
    """Skip source sentences that mostly restate a title or previously kept line."""
    normalized_candidate = _normalized_sentence_text(candidate)
    if not normalized_candidate:
        return False
    candidate_words = normalized_candidate.split()
    for existing in existing_sentences:
        normalized_existing = _normalized_sentence_text(existing)
        if not normalized_existing:
            continue
        if (
            normalized_candidate == normalized_existing
            or normalized_candidate.startswith(normalized_existing)
            or normalized_existing.startswith(normalized_candidate)
        ):
            return True
        existing_words = normalized_existing.split()
        overlap = len(set(candidate_words) & set(existing_words))
        threshold = min(len(candidate_words), len(existing_words))
        if threshold >= 6 and overlap >= max(6, int(threshold * 0.8)):
            return True
    return False


def _normalized_sentence_text(text: str) -> str:
    """Reduce punctuation noise before comparing near-duplicate news sentences."""
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


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
        # Only treat straight single quotes as quoted copy when they wrap a
        # standalone phrase. This avoids false positives on normal possessives
        # like "Instagram's" or contractions like "don't".
        r"(?<![a-z0-9])'[^']+\s[^']*'(?![a-z0-9])",
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
