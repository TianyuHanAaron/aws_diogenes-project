"""Stage runner for the YAML-driven Flower & Festival workflow."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from html import escape
from typing import Any

from tools.fetch_local_photos_tool import FetchLocalPhotosTool


logger = logging.getLogger(__name__)
SEASONAL_IMAGE_TOOL = FetchLocalPhotosTool()
FALLBACK_FOCUS = "Seasonal Culture - Current Meaning"


async def generate_seasonal_section(events, request, current_dt, window_end) -> str:
    """Render the seasonal section without remote seasonal retrieval dependencies."""
    print("Seasonal section: building fallback festivals and flowers...")
    return await build_seasonal_fallback_section(request, current_dt, window_end)


async def build_seasonal_fallback_section(request, current_dt, window_end) -> str:
    """Render a publishable fallback section when seasonal retrieval is unavailable."""
    fallback_entries = _static_fallback_seasonal_entries(request.location, request.hemisphere, current_dt, window_end)
    enriched_entries = await _attach_illustrations(fallback_entries, request.location)
    return _build_seasonal_html(enriched_entries)


def _static_fallback_seasonal_entries(
    location: str,
    hemisphere: str,
    current_dt,
    window_end,
) -> list[dict[str, str]]:
    """Create a deterministic 2-festival and 2-flower set without location-specific flora.

    The fallback is intentionally simple and inspectable:
    - start from a short ordered festival calendar inside the digest window
    - then add two globally recognizable flower-season entries
    - finally trim to the exact 2 + 2 shape we want to render
    """
    entries: list[dict[str, str]] = []
    for event_date, event in _festival_candidates_for_window(current_dt, hemisphere):
        if current_dt.date() <= event_date <= window_end.date():
            entries.append(event)
        if len([entry for entry in entries if entry.get("badge") == "Festival"]) >= 2:
            break

    entries.extend(_flower_candidates_for_hemisphere(hemisphere))
    return _select_seasonal_entries(entries)


def _festival_candidates_for_window(current_dt, hemisphere: str) -> list[tuple[datetime.date, dict[str, str]]]:
    """Return the ordered list of festival candidates used by the fallback seasonal section."""
    season_name = "Autumn Equinox" if hemisphere.lower() == "southern" else "Spring Equinox"
    return [
        (
            datetime(current_dt.year, 3, 17, tzinfo=current_dt.tzinfo).date(),
            {
                "title": "St Patrick's Day",
                "badge": "Festival",
                "paragraph": (
                    "St Patrick's Day falls on March 17 and sits inside the current two-week digest window as an upcoming "
                    "public festival tied to Irish heritage. It began as a feast day associated with Saint Patrick and is now "
                    "marked with parades, green dress, music, public gatherings, and civic celebrations across Ireland, North "
                    "America, Oceania, and many diaspora communities."
                ),
                "focus": "Irish Culture - Public Celebration",
                "image_query": "St Patrick's Day parade green celebration",
            },
        ),
        (
            datetime(current_dt.year, 3, 20, tzinfo=current_dt.tzinfo).date(),
            {
                "title": "Nowruz",
                "badge": "Festival",
                "paragraph": (
                    "Nowruz falls around March 20 or 21 and marks the Persian New Year at the spring equinox. It is observed "
                    "across Iran, Central Asia, Afghanistan, the Caucasus, Kurdish communities, and many diaspora households "
                    "with symbolic tables, visits, shared meals, home preparation, and public cultural events that emphasize "
                    "renewal at the start of a new seasonal cycle."
                ),
                "focus": "New Year - Renewal",
                "image_query": "Nowruz haft seen celebration",
            },
        ),
        (
            datetime(current_dt.year, 3, 28, tzinfo=current_dt.tzinfo).date(),
            {
                "title": "Earth Hour",
                "badge": "Festival",
                "paragraph": (
                    "Earth Hour is observed globally in late March and brings together households, landmarks, and public "
                    "institutions for a coordinated lights-out moment linked to environmental awareness. The event is widely "
                    "supported by civic groups, city governments, and community campaigns, making it a practical late-March "
                    "festival anchor when the digest window extends beyond the equinox."
                ),
                "focus": "Environmental Action - Public Participation",
                "image_query": "Earth Hour city lights off event",
            },
        ),
        (
            datetime(current_dt.year, 3, 21, tzinfo=current_dt.tzinfo).date(),
            {
                "title": season_name,
                "badge": "Festival",
                "paragraph": (
                    f"The {season_name.lower()} falls inside the current digest window and marks a seasonal turning point that "
                    "has long anchored calendar rituals, public gatherings, and broader cultural observances in many regions. "
                    "Even where it is not treated as a single formal holiday, it remains a widely recognized seasonal milestone "
                    "for festivals, ceremonies, and public programming tied to renewal and changing daylight."
                ),
                "focus": "Seasonal Change - Public Observance",
                "image_query": f"{season_name} celebration",
            },
        ),
    ]


def _flower_candidates_for_hemisphere(hemisphere: str) -> list[dict[str, str]]:
    """Return the ordered list of flower-season entries used by the fallback section."""
    season_word = "Autumn" if hemisphere.lower() == "southern" else "Spring"
    return [
        {
            "title": "Cherry Blossom Season",
            "badge": "International Flower",
            "paragraph": (
                "Cherry blossom season is one of the most recognizable flower periods in the global calendar, with early "
                "blooms drawing attention across Japan, Korea, China, Washington, and other spring landscapes. The season "
                "is culturally linked to public viewing traditions, short-lived beauty, and the idea of renewal, which is "
                "why it remains a strong international flower reference point for March."
            ),
            "focus": "Japanese Culture - Hanami",
            "image_query": "cherry blossom hanami park",
        },
        {
            "title": f"{season_word} Tulip Season",
            "badge": "International Flower",
            "paragraph": (
                f"{season_word} tulip displays are one of the clearest flower markers in the wider seasonal calendar, especially "
                "across public gardens and large bulb plantings in Europe and other temperate regions. The bloom is valued for "
                "dense colour, formal garden design, and the way it signals the arrival of a new flower season in parks, "
                "botanical collections, and public festivals."
            ),
            "focus": f"{season_word} Gardens - Tulips",
            "image_query": f"{season_word.lower()} tulip garden bloom",
        },
    ]


def _select_seasonal_entries(entries: list[dict[str, str]]) -> list[dict[str, str]]:
    """Keep exactly two festivals and two flower entries whenever possible."""
    festivals = [entry for entry in entries if entry.get("badge") == "Festival"]
    flowers = [entry for entry in entries if entry.get("badge") != "Festival"]
    ordered = festivals[:2] + flowers[:2]
    return ordered[:4]


async def _attach_illustrations(entries: list[dict[str, str]], location: str) -> list[dict[str, str]]:
    """Attach one representative image URL to each festival or flora entry."""
    if not entries:
        return []
    return await asyncio.gather(*[_attach_single_illustration(entry, location) for entry in entries])


async def _attach_single_illustration(entry: dict[str, str], location: str) -> dict[str, str]:
    """Fetch one usable illustration URL for a seasonal entry."""
    queries = _image_query_candidates(entry, location)
    image_url = await asyncio.to_thread(_fetch_seasonal_image_url, queries)
    enriched = dict(entry)
    enriched["image_url"] = image_url
    return enriched


def _image_query_candidates(entry: dict[str, str], location: str) -> list[str]:
    """Build a small ordered list of image queries for one seasonal entry."""
    queries = [
        entry.get("image_query", ""),
        _default_image_query(entry.get("title", ""), entry.get("badge", ""), entry.get("focus", ""), location),
        f'{entry.get("title", "")} {entry.get("focus", "")}'.strip(),
    ]
    if "flora" in entry.get("badge", "").lower() or "flower" in entry.get("badge", "").lower():
        queries.append(f'{entry.get("title", "")} blossom'.strip())
    else:
        queries.append(f'{entry.get("title", "")} festival celebration'.strip())
    seen: set[str] = set()
    cleaned_queries: list[str] = []
    for query in queries:
        cleaned = _clean_text(query)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            cleaned_queries.append(cleaned)
    return cleaned_queries


def _fetch_seasonal_image_url(queries: list[str]) -> str:
    """Try several image queries and return the first usable seasonal illustration URL."""
    for query in queries:
        for fetcher_name in ("fetch_pexels", "fetch_unsplash", "fetch_pixabay"):
            fetcher = getattr(SEASONAL_IMAGE_TOOL, fetcher_name)
            try:
                for item in fetcher(query):
                    image_url = _extract_image_url(item)
                    if image_url:
                        return image_url
            except Exception as exc:
                logger.warning("Seasonal image fetch failed for %s with %s: %s", query, fetcher_name, exc)
                continue
    return ""


def _extract_image_url(item: dict[str, Any]) -> str:
    """Pick the best direct image URL from a mixed provider payload."""
    candidates = [
        item.get("src", {}).get("original"),
        item.get("src", {}).get("large"),
        item.get("src", {}).get("medium"),
        item.get("urls", {}).get("regular"),
        item.get("urls", {}).get("small"),
        item.get("largeImageURL"),
        item.get("webformatURL"),
        item.get("url"),
    ]
    for candidate in candidates:
        value = str(candidate or "").strip()
        if value.startswith("https://") and " " not in value:
            return value
    return ""


def _build_seasonal_html(entries: list[dict[str, str]]) -> str:
    """Render a deterministic fallback layout for seasonal entries."""
    blocks: list[str] = []
    for entry in entries:
        image_html = ""
        image_url = entry.get("image_url", "")
        if image_url:
            image_html = (
                '<div style="margin:12px 0 12px 0;">'
                f'<img src="{escape(image_url)}" alt="{escape(entry["title"])}" '
                'style="display:block;width:100%;max-height:240px;height:auto;object-fit:cover;'
                'border:0;outline:none;text-decoration:none;border-radius:8px;">'
                "</div>"
            )
        blocks.append(
            '<div class="event">'
            f'<span class="badge">{escape(entry["badge"])}</span>'
            f'<strong>{escape(entry["title"])}</strong>'
            f"{image_html}"
            '<div class="news-description" style="margin-top:0;font-size:13px;color:#374151;">'
            f'<strong>Focus:</strong> {escape(entry["focus"])}'
            "</div>"
            f'<div class="news-description">{escape(entry["paragraph"])}</div>'
            "</div>"
        )
    return "".join(blocks)


def _clean_focus(raw_focus: Any) -> str:
    """Normalize the short focus line shown under each entry."""
    focus = _clean_text(raw_focus)
    focus = re.sub(r"^focus:\s*", "", focus, flags=re.IGNORECASE)
    focus = re.sub(r"\s*-\s*", " - ", focus)
    if not focus:
        return FALLBACK_FOCUS
    parts = [part.strip(" -") for part in focus.split(" - ") if part.strip(" -")]
    if len(parts) >= 2:
        return f"{parts[0]} - {parts[1]}"
    return f"{parts[0]} - Cultural Meaning" if parts else FALLBACK_FOCUS


def _default_image_query(title: str, badge: str, focus: str, location: str) -> str:
    """Build a practical default image-search phrase when the agent omits one."""
    title_text = _clean_text(title)
    focus_terms = [part.strip() for part in _clean_focus(focus).split(" - ") if part.strip()]
    if "flower" in badge.lower():
        return f"{title_text} blossom {focus_terms[0] if focus_terms else ''}".strip()
    return f"{title_text} festival {focus_terms[0] if focus_terms else 'celebration'}".strip()


def _clean_text(value: Any) -> str:
    """Collapse whitespace and strip any accidental markup from model text."""
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()
