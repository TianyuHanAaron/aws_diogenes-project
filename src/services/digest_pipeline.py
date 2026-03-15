"""Digest orchestration and section-level rendering."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
from datetime import datetime, timedelta, timezone
from html import escape, unescape as html_unescape
from pathlib import Path
from zoneinfo import ZoneInfo

from crews.news_digest.news_digest import generate_news_digest
from crews.photo_album.photo_album import generate_photo_album
from crews.seasonal_events.seasonal_events import build_seasonal_fallback_section, generate_seasonal_section
from models import CityLandmark, DigestInputs, DigestResult, NewsItem, PhotoCandidate, SeasonalEventResult, UserRequest
from services.email_sender import send_digest_email_async
from tools.fetch_city_landmarks_tool import FetchCityLandmarksTool
from tools.fetch_local_photos_tool import FetchLocalPhotosTool
from tools.fetch_news_tool import FetchNewsTool


logger = logging.getLogger(__name__)
TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "email_template.html"
STATE_DIR = Path("/tmp") if os.getenv("AWS_LAMBDA_FUNCTION_NAME") else Path.cwd()
METADATA_PATH = STATE_DIR / "last_digest_metadata.json"
LOCAL_PREVIEW_PATH = Path(__file__).resolve().parent.parent / "email_digest.html"
PIPELINE_VERSION = "direct-render-2026-03-15-news-v3-seasonal-v2"
DEFAULT_CHANNELS = ["global", "interest"]
NEWS_CHANNEL_ORDER = ("global", "local", "investment", "interest")
NO_NEWS_HTML = '<div class="news-description">No grounded news developments were available for this digest.</div>'
NO_WEBCAMS_HTML = '<div class="news-description">No live webcam links were available for this run.</div>'
NO_PHOTOS_HTML = '<div class="caption">No local photographs were available for this run.</div>'
IMPORTANT_NEWS_PATTERNS = [
    re.compile(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:,\s+\d{4})?\b"),
    re.compile(r"\b\d+(?:\.\d+)?\s?(?:%|percent|million|billion|trillion)\b", flags=re.IGNORECASE),
    re.compile(r"\b(?:central bank|interest rates?|inflation|tariffs?|sanctions?|trade policy|ceasefire|earnings|oil prices?|gas prices?|military deployment|internet shutdown|budget|regulation|artificial intelligence)\b", flags=re.IGNORECASE),
    re.compile(r"\b(?:White House|Pentagon|Congress|Parliament|Supreme Court|Federal Reserve|Reserve Bank|Treasury|Meta|Microsoft|Google|Amazon|NATO|UN|EU|ECB|RBA|ASX|NYSE|Nasdaq)\b"),
]
IMPORTANT_ENTITY_PATTERN = re.compile(
    r"\b(?:[A-Z]{2,}|[A-Z][a-z]+)(?:\s+(?:[A-Z]{2,}|[A-Z][a-z]+|of|the|for|and|to)){1,4}\b"
)
PEOPLE_FOCUSED_PHOTO_PATTERNS = [
    re.compile(pattern, flags=re.IGNORECASE)
    for pattern in [
        r"\bportrait\b",
        r"\bportraits\b",
        r"\bselfie\b",
        r"\bheadshot\b",
        r"\bclose[- ]up\b",
        r"\bface\b",
        r"\bfaces\b",
        r"\bperson\b",
        r"\bpeople\b",
        r"\bcrowd\b",
        r"\bman\b",
        r"\bmen\b",
        r"\bwoman\b",
        r"\bwomen\b",
        r"\bcouple\b",
        r"\bchild\b",
        r"\bchildren\b",
        r"\bfriends\b",
        r"\bmodel\b",
        r"\bsmiling\b",
        r"\bbride\b",
        r"\bgroom\b",
    ]
]


class DigestPipelineService:
    """Coordinates tools, crews, and final email assembly."""

    def __init__(
        self,
        news_tool: FetchNewsTool | None = None,
        city_landmarks_tool: FetchCityLandmarksTool | None = None,
        photos_tool: FetchLocalPhotosTool | None = None,
    ):
        self.news_tool = news_tool or FetchNewsTool()
        self.city_landmarks_tool = city_landmarks_tool or FetchCityLandmarksTool()
        self.photos_tool = photos_tool or FetchLocalPhotosTool()

    # Public API
    async def build_request(self, payload: dict | None = None) -> UserRequest:
        """Normalize the inbound payload and apply the default date window."""
        payload = payload or {}
        request = UserRequest.model_validate(payload)
        now = datetime.now(ZoneInfo("Australia/Sydney"))
        if not request.channels:
            # Keep empty local profiles from producing a blank news digest.
            request.channels = DEFAULT_CHANNELS.copy()
        if not request.month:
            request.month = now.strftime("%B")
        request.until = now.isoformat()
        if not request.since:
            request.since = (
                await self._load_last_digest_timestamp()
                or now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
            )
        return request

    async def collect_inputs(self, request: UserRequest) -> DigestInputs:
        """Fetch all independent source inputs concurrently."""
        news, seasonal_events, landmarks, photos = await asyncio.gather(
            self._collect_news(request),
            self._collect_seasonal_events(request),
            self._collect_landmarks(request),
            self._collect_photos(request),
        )
        return DigestInputs(
            request=request,
            news=news,
            seasonal_events=seasonal_events,
            landmarks=landmarks,
            photos=photos,
        )

    async def generate_digest(self, inputs: DigestInputs) -> DigestResult:
        """Render the final HTML email and remember rotation metadata keys."""
        logger.info(
            "Digest pipeline version=%s news=%d seasonal=%d landmarks=%d photos=%d",
            PIPELINE_VERSION,
            len(inputs.news),
            len(inputs.seasonal_events),
            len(inputs.landmarks),
            len(inputs.photos),
        )
        print("Assembling seasonal events section...")
        print("Assembling world-at-glance section...")
        print("Assembling news digest section...")
        print("Assembling photograph album section...")
        html, photo_keys, webcam_links = await self._render_html_digest(inputs)
        print("Email sections assembled")
        return DigestResult(html=html, raw="", photo_keys=photo_keys, webcam_links=webcam_links)

    async def deliver_digest(self, request: UserRequest, digest: DigestResult) -> None:
        """Send the digest and persist send metadata when delivery succeeds."""
        if not request.email:
            return
        await send_digest_email_async(
            receiver_email=request.email,
            subject="Diogenes Sunlight Post",
            body=digest.html,
        )
        await self._save_digest_metadata(
            last_sent_at=request.until or datetime.now(ZoneInfo("Australia/Sydney")).isoformat(),
            last_photo_keys=digest.photo_keys,
            last_webcam_links=digest.webcam_links,
        )

    async def save_digest(self, digest: DigestResult, output_dir: Path) -> Path:
        """Write the rendered digest to disk."""
        output_path = output_dir / "email_digest.html"
        await asyncio.to_thread(output_path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(output_path.write_text, digest.html, encoding="utf-8")
        if not os.getenv("AWS_LAMBDA_FUNCTION_NAME") and output_path != LOCAL_PREVIEW_PATH:
            await asyncio.to_thread(LOCAL_PREVIEW_PATH.write_text, digest.html, encoding="utf-8")
        return output_path

    # Tool collection
    async def _collect_news(self, request: UserRequest) -> list[NewsItem]:
        """Fetch and pre-clean raw news items."""
        try:
            news = [NewsItem.from_raw(item) for item in await self.news_tool.arun(query=request.topic)]
            return self._prepare_news_items(self._filter_news_by_window(news, request))
        except RuntimeError as exc:
            if "NEWSAPI_API_KEY is not set" in str(exc):
                logger.warning("NEWSAPI_API_KEY not set; continuing without news")
                return []
            raise

    async def _collect_seasonal_events(self, request: UserRequest) -> list[SeasonalEventResult]:
        """Skip remote seasonal retrieval and rely on the local fallback section builder."""
        logger.info("Seasonal event retrieval disabled; using local fallback section")
        return []

    async def _collect_landmarks(self, request: UserRequest) -> list[CityLandmark]:
        """Fetch world webcam links for the glance section."""
        try:
            camera_data = await self.city_landmarks_tool.arun(location=request.location)
            return [CityLandmark.from_raw(item) for item in camera_data.get("landmarks", [])]
        except Exception as exc:
            logger.warning("City landmarks collection failed: %s", exc)
            return []

    async def _collect_photos(self, request: UserRequest) -> list[PhotoCandidate]:
        """Fetch city and fallback scene photography candidates."""
        try:
            return [
                PhotoCandidate.from_raw(item, fallback_location=request.location)
                for item in await self.photos_tool.arun(location=request.location)
            ]
        except Exception as exc:
            logger.warning("Photo collection failed: %s", exc)
            return []

    # Template assembly
    async def _render_html_digest(self, inputs: DigestInputs) -> tuple[str, list[str], list[str]]:
        """Render all major sections, then inject them into the HTML template."""
        template, metadata = await asyncio.gather(
            asyncio.to_thread(TEMPLATE_PATH.read_text, encoding="utf-8"),
            self._load_digest_metadata(),
        )
        (photos_html, photo_keys), (landmarks_html, webcam_links), seasonal_html, news_html = await asyncio.gather(
            self._render_photos(inputs.photos, inputs.request.location, metadata),
            self._render_live_city_landmarks(inputs.landmarks, inputs.request.location, metadata),
            self._render_seasonal_events(inputs.request, inputs.seasonal_events),
            self._render_news_sections(inputs.news, inputs.request),
        )

        replacements = {
            "{{title}}": escape("Diogenes Sunlight Post"),
            "{{season_background}}": self._season_background(inputs.request.hemisphere, inputs.request.month),
            "{{date}}": escape(datetime.now(ZoneInfo("Australia/Sydney")).strftime("%B %d, %Y")),
            "{{seasonal_events}}": seasonal_html,
            "{{live_city_landmarks}}": landmarks_html,
            "{{news_sections}}": news_html,
            "{{photo_section_title}}": escape(f"{self._display_city_name(inputs.request.location)} Photograph Album"),
            "{{photos}}": photos_html,
        }
        return self._apply_template_replacements(template, replacements), photo_keys, webcam_links

    # Section rendering
    async def _render_seasonal_events(self, request: UserRequest, events: list[SeasonalEventResult]) -> str:
        """Prefer the agent-built seasonal section and fall back to deterministic copy."""
        current_dt = self._parse_iso_datetime(request.until) or datetime.now(ZoneInfo("Australia/Sydney"))
        window_end = current_dt + timedelta(days=14)
        try:
            html = await generate_seasonal_section(events, request, current_dt, window_end)
            if '<div class="event">' in html and "..." not in html and "…" not in html:
                logger.info("Seasonal section rendered via direct Nova path")
                return html
        except Exception as exc:
            logger.warning("Seasonal section generation failed: %s", exc)
        logger.info("Seasonal section using fallback path")
        return await build_seasonal_fallback_section(request, current_dt, window_end)

    async def _render_news_sections(self, news_items: list[NewsItem], request: UserRequest) -> str:
        """Render only the selected news sections using the grouped digest output."""
        selected = self._selected_channel_names(request)
        timeframe_note = (
            '<div class="news-description" style="margin-bottom:18px;">'
            f'{escape(self._news_timeframe_label(request))}'
            "</div>"
        )
        grouped = await generate_news_digest(news_items, request)
        sections: list[str] = []
        for name in NEWS_CHANNEL_ORDER:
            if name not in selected:
                continue
            items = grouped.get(name, [])
            if not items:
                continue
            sections.append(self._render_news_group(name, items))
        if not sections:
            return NO_NEWS_HTML
        return timeframe_note + "".join(sections)

    async def _render_live_city_landmarks(
        self,
        landmarks: list[CityLandmark],
        location: str,
        metadata: dict | None = None,
    ) -> tuple[str, list[str]]:
        """Render up to three world webcam buttons while rotating away from the last batch."""
        logger.info("City glance rendering landmarks=%d for %s", len(landmarks), location)
        if not landmarks:
            return NO_WEBCAMS_HTML, []
        metadata = metadata or {}
        last_links = {
            str(link)
            for link in metadata.get("last_webcam_links", [])
            if str(link)
        }
        rows = []
        selected_links: list[str] = []
        candidates = self._randomized_landmarks(landmarks)
        fresh_candidates = [
            landmark for landmark in candidates if (landmark.stream or landmark.image or "") not in last_links
        ]
        for landmark in (fresh_candidates or candidates)[:3]:
            link = landmark.stream or landmark.image
            if not link:
                continue
            selected_links.append(link)
            rows.append(
                '<tr><td style="padding:0 0 12px 0;">'
                f'<a href="{escape(link)}" target="_blank" rel="noopener noreferrer" '
                'style="display:block;background:#2563eb;color:#ffffff;text-decoration:none;'
                'font-weight:600;font-size:14px;line-height:1.4;padding:14px 16px;'
                'border-radius:8px;text-align:center;">'
                f'{escape(landmark.name)}'
                "</a>"
                "</td></tr>"
            )
        if not rows:
            return NO_WEBCAMS_HTML, []
        return (
            '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" '
            'style="width:100%;border-collapse:collapse;">'
            f'{"".join(rows)}'
            "</table>",
            selected_links,
        )

    async def _render_photos(
        self,
        photos: list[PhotoCandidate],
        location: str,
        metadata: dict | None = None,
    ) -> tuple[str, list[str]]:
        """Render the photograph album, with an agent path first and a safe HTML fallback second."""
        photo_inputs = self._build_photo_inputs(photos)
        if not photo_inputs:
            logger.info("Photo album had no usable image URLs")
            return NO_PHOTOS_HTML, []
        metadata = metadata or {}
        photo_inputs = self._randomized_photo_inputs(photo_inputs, metadata)
        try:
            html, photo_keys = await generate_photo_album(
                photo_inputs[:24],
                location,
                metadata.get("last_photo_keys", []),
            )
            if html:
                logger.info("Photo album rendered via direct Nova path")
                return html, photo_keys
        except Exception as exc:
            logger.warning("Photo album generation failed: %s", exc)
        logger.info("Photo album using deterministic fallback path")
        return self._photo_fallback(photo_inputs, location)

    def _selected_channel_names(self, request: UserRequest) -> set[str]:
        """Return selected channel ids in the normalized form used by render helpers."""
        return {channel.lower() for channel in request.channels}

    def _apply_template_replacements(self, template: str, replacements: dict[str, str]) -> str:
        """Apply placeholder replacements in one small, readable pass."""
        rendered = template
        for placeholder, value in replacements.items():
            rendered = rendered.replace(placeholder, value)
        return rendered

    def _news_section_label(self, channel: str) -> str:
        """Map an internal channel id to the display title used in the email."""
        labels = {
            "global": "Global",
            "local": "Local",
            "investment": "Investment",
            "interest": "Interest",
        }
        return labels[channel]

    def _render_news_group(self, channel: str, items: list[dict]) -> str:
        """Render one populated news section from already-ranked summaries."""
        blocks = []
        for item in items:
            rank = int(item.get("rank", len(blocks) + 1) or len(blocks) + 1)
            summary = str(item.get("summary", "") or "").strip()
            if not summary:
                continue
            blocks.append(
                '<div class="news-item">'
                '<div class="news-description" style="font-size:16px;line-height:1.85;color:#374151;">'
                f'<span style="display:inline-block;min-width:24px;font-weight:700;color:#111827;">{rank}.</span> '
                f'{self._format_news_summary_html(summary)}'
                '</div>'
                "</div>"
            )
        return (
            '<div class="news-group">'
            '<div class="news-group-title" '
            'style="display:inline-block;margin:0 0 14px 0;padding:6px 12px;font-size:12px;'
            'font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#111827;'
            'background:#f3f4f6;border:1px solid #d1d5db;border-radius:999px;">'
            f'{self._news_section_label(channel)}'
            '</div>'
            f'{"".join(blocks) if blocks else "<div class=\"news-description\">No qualifying developments were available for this section.</div>"}'
            "</div>"
        )

    def _build_photo_inputs(self, photos: list[PhotoCandidate]) -> list[dict]:
        """Convert raw photo candidates into the smaller structure used by album rendering.

        The deterministic filtering rules are:
        1. keep only candidates with a renderable direct image URL
        2. reject images whose metadata suggests visible faces or portraits
        3. keep a compact metadata summary for the captioning step
        """
        photo_inputs: list[dict] = []
        for index, photo in enumerate(photos, start=1):
            photo_input = self._photo_input_from_candidate(photo, index)
            if photo_input:
                photo_inputs.append(photo_input)
        return photo_inputs

    def _photo_input_from_candidate(self, photo: PhotoCandidate, index: int) -> dict | None:
        """Build one publishable photo input or return `None` if it should be skipped."""
        image_url = self._best_photo_url(photo)
        if not self._is_probable_image_url(image_url):
            return None

        source_text = self._photo_source_text(photo)
        if self._looks_like_people_focused_photo(photo, source_text):
            return None

        return {
            "id": index,
            "photo_key": self._photo_key(photo) or f"photo-{index}",
            "image_url": image_url,
            "location": photo.location,
            "source": photo.source,
            "source_text": source_text,
        }

    def _photo_source_text(self, photo: PhotoCandidate) -> str:
        """Build the short source text passed to the photo captioning step."""
        tags = photo.raw.get("tags", "")
        if isinstance(tags, list):
            tags = " ".join(str(tag) for tag in tags)
        return " ".join(
            filter(
                None,
                [
                    photo.location,
                    photo.photographer,
                    str(photo.raw.get("alt") or ""),
                    str(photo.raw.get("description") or ""),
                    str(photo.raw.get("alt_description") or ""),
                    str(photo.raw.get("title") or ""),
                    str(tags or ""),
                ],
            )
        )

    def _format_news_summary_html(self, summary: str) -> str:
        """Add light emphasis so long news paragraphs are easier to scan in email."""
        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", self._clean_news_text(summary))
            if sentence.strip()
        ]
        if not sentences:
            return escape(summary)
        # Make the first sentence visually lead the paragraph, then lightly
        # highlight dates, institutions, and policy terms throughout.
        lead = self._highlight_news_concepts_html(sentences[0])
        rest = " ".join(self._highlight_news_concepts_html(sentence) for sentence in sentences[1:])
        lead_html = f'<span style="font-weight:600;color:#111827;">{lead}</span>'
        return lead_html if not rest else f"{lead_html} {rest}"

    def _highlight_news_concepts_html(self, text: str) -> str:
        """Highlight dates, institutions, and policy terms inside one summary segment."""
        spans = self._merge_text_spans(self._news_highlight_spans(text))
        if not spans:
            return escape(text)

        parts: list[str] = []
        cursor = 0
        for start, end in spans[:8]:
            parts.append(escape(text[cursor:start]))
            parts.append(
                '<span style="font-weight:600;color:#111827;">'
                f'{escape(text[start:end])}'
                "</span>"
            )
            cursor = end
        parts.append(escape(text[cursor:]))
        return "".join(parts)

    def _news_highlight_spans(self, text: str) -> list[tuple[int, int]]:
        """Find important phrases worth styling inside long news paragraphs."""
        spans: list[tuple[int, int]] = []
        for pattern in IMPORTANT_NEWS_PATTERNS:
            spans.extend((match.start(), match.end()) for match in pattern.finditer(text))
        for match in IMPORTANT_ENTITY_PATTERN.finditer(text):
            phrase = match.group(0).strip()
            if len(phrase) >= 6:
                spans.append((match.start(), match.end()))
        return spans

    def _merge_text_spans(self, spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
        """Merge overlapping highlight spans so the rendered HTML stays valid."""
        merged: list[list[int]] = []
        for start, end in sorted(spans, key=lambda item: (item[0], -(item[1] - item[0]))):
            if not merged or start >= merged[-1][1]:
                merged.append([start, end])
                continue
            merged[-1][1] = max(merged[-1][1], end)
        return [(start, end) for start, end in merged]

    def _looks_like_people_focused_photo(self, photo: PhotoCandidate, source_text: str) -> bool:
        """Reject photos whose metadata strongly suggests visible faces or portraits."""
        raw = photo.raw or {}
        text = " ".join(
            [
                source_text,
                str(raw.get("caption") or ""),
                str(raw.get("slug") or ""),
            ]
        ).lower()
        return any(pattern.search(text) for pattern in PEOPLE_FOCUSED_PHOTO_PATTERNS)

    def _prepare_news_items(self, news_items: list[NewsItem]) -> list[NewsItem]:
        """Deduplicate and clean raw fetched news before it reaches the news crew.

        This preprocessing stays deterministic on purpose. It does only three
        things: clean text, reject obvious newsletter/promotional noise, and
        remove duplicates so the agent stages start from a clearer pool.
        """
        prepared: list[NewsItem] = []
        seen_keys: set[str] = set()
        for item in news_items:
            candidate = self._clean_candidate_news_item(item)
            if not candidate:
                continue
            key = self._news_item_key(candidate)
            if not self._should_keep_prepared_news_item(candidate, key, seen_keys):
                continue
            seen_keys.add(key)
            prepared.append(candidate)
        return prepared

    def _clean_candidate_news_item(self, item: NewsItem) -> NewsItem | None:
        """Return a cleaned news item or `None` when the fetched item has no usable title."""
        title = self._clean_news_text(item.title)
        if not title:
            return None
        return NewsItem(
            title=title,
            summary=self._clean_news_text(item.summary),
            body=self._clean_news_text(item.body),
            url=item.url,
            source=self._clean_news_text(item.source),
            published=item.published,
        )

    def _should_keep_prepared_news_item(self, item: NewsItem, key: str, seen_keys: set[str]) -> bool:
        """Apply the deterministic keep/drop rules for cleaned news items."""
        if not key:
            return False
        if key in seen_keys:
            return False
        if self._looks_like_promotional_news(item):
            return False
        return True

    def _looks_like_promotional_news(self, item: NewsItem) -> bool:
        """Screen out newsletter-style feed items before digest generation."""
        lowered = " ".join([item.title, item.summary, item.source]).lower()
        return self._looks_like_marketing_copy(lowered)

    def _looks_like_marketing_copy(self, lowered: str) -> bool:
        """Filter phrases that usually indicate newsletters or promotional copy."""
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

    def _clean_news_text(self, text: str) -> str:
        """Strip HTML and collapse whitespace in provider-supplied news text."""
        cleaned = html_unescape(str(text or ""))
        cleaned = re.sub(r"<[^>]+>", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def _news_item_key(self, item: NewsItem) -> str:
        """Build the deduplication key used for cleaned news items."""
        if item.url:
            return item.url.strip().lower()
        return self._normalized_text_key(item.title)

    def _normalized_text_key(self, text: str) -> str:
        """Normalize text into a loose alphanumeric key for repeat detection."""
        lowered = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
        return lowered

    def _photo_fallback(self, photo_inputs: list[dict], location: str) -> tuple[str, list[str]]:
        """Render a deterministic album layout if the photo crew returns bad HTML."""
        rows = []
        selected = photo_inputs[:10]
        for item in selected:
            caption = item.get("source_text") or f"Street scene in {location}."
            image_url = str(item.get("image_url") or "")
            rows.append(
                "<tr><td style=\"padding:0 0 16px 0;\">"
                '<div class="photo-card" style="border-radius:8px;overflow:hidden;background:#fafafa;border:1px solid #eee;">'
                f'<a href="{escape(image_url)}" target="_blank" rel="noopener noreferrer" style="text-decoration:none;color:inherit;display:block;">'
                f'<img src="{escape(image_url)}" alt="{escape(caption)}" style="display:block;width:100%;max-width:100%;height:auto;object-fit:cover;border:0;outline:none;text-decoration:none;" />'
                '</a>'
                f'<div class="caption" style="font-size:14px;line-height:1.65;padding:12px 14px;color:#374151;white-space:normal;overflow-wrap:anywhere;word-break:break-word;">{escape(caption)}<br><a href="{escape(image_url)}" target="_blank" rel="noopener noreferrer">View image</a></div>'
                "</div></td></tr>"
            )
        return "".join(rows), [str(item.get("photo_key") or "") for item in selected]

    def _randomized_landmarks(self, landmarks: list[CityLandmark]) -> list[CityLandmark]:
        """Shuffle landmarks so repeated runs are less likely to show the same order."""
        shuffled = list(landmarks)
        random.SystemRandom().shuffle(shuffled)
        return shuffled

    def _randomized_photo_inputs(self, photo_inputs: list[dict], metadata: dict) -> list[dict]:
        """Prefer photos that were not used in the previous digest run.

        The order is deterministic in spirit, but with one small shuffle:
        - keep fresh photos ahead of repeated ones
        - shuffle inside each bucket so consecutive digests do not look identical
        """
        last_photo_keys = {
            str(key)
            for key in metadata.get("last_photo_keys", [])
            if str(key)
        }
        fresh = [
            item for item in photo_inputs if str(item.get("photo_key") or "") not in last_photo_keys
        ]
        repeated = [
            item for item in photo_inputs if str(item.get("photo_key") or "") in last_photo_keys
        ]
        random.SystemRandom().shuffle(fresh)
        random.SystemRandom().shuffle(repeated)
        return fresh + repeated

    # Shared parsing helpers
    def _best_photo_url(self, photo: PhotoCandidate) -> str:
        """Pick the best direct image URL available from a mixed provider payload."""
        raw = photo.raw or {}
        for candidate in [
            photo.url,
            raw.get("src", {}).get("original"),
            raw.get("src", {}).get("large"),
            raw.get("src", {}).get("medium"),
            raw.get("urls", {}).get("full"),
            raw.get("urls", {}).get("regular"),
            raw.get("urls", {}).get("small"),
            raw.get("largeImageURL"),
            raw.get("webformatURL"),
            raw.get("url"),
        ]:
            value = str(candidate or "").strip()
            if self._is_probable_image_url(value):
                return value
        return ""

    def _is_probable_image_url(self, url: str) -> bool:
        """Keep only direct image assets that are likely to render inside email clients."""
        value = (url or "").strip()
        if not value.startswith("http"):
            return False
        if any(
            host in value
            for host in [
                "images.pexels.com",
                "images.unsplash.com",
                "cdn.pixabay.com",
                "pixabay.com/get/",
            ]
        ):
            return True
        return bool(re.search(r"\.(jpg|jpeg|png|webp)(?:\?|$)", value, flags=re.IGNORECASE))

    def _photo_key(self, photo: PhotoCandidate) -> str:
        """Build a stable photo key for repeat-avoidance metadata."""
        return str(photo.photo_id or self._best_photo_url(photo) or "").strip()

    def _display_city_name(self, location: str) -> str:
        """Convert a full location string into the shorter title-case city label."""
        cleaned = (location or "").strip()
        if not cleaned:
            return "City"
        parts = [part.strip() for part in cleaned.split(",") if part.strip()]
        first = parts[0] if parts else cleaned
        return " ".join(word.capitalize() for word in first.split())

    # Time and metadata helpers
    def _filter_news_by_window(self, news: list[NewsItem], request: UserRequest) -> list[NewsItem]:
        """Keep items whose publish time falls inside the current digest window."""
        since_dt = self._parse_iso_datetime(request.since)
        until_dt = self._parse_iso_datetime(request.until)
        if not since_dt or not until_dt:
            return news
        filtered: list[NewsItem] = []
        for item in news:
            published_dt = self._parse_published_datetime(item.published)
            if not published_dt or since_dt <= published_dt <= until_dt:
                filtered.append(item)
        return filtered

    def _parse_published_datetime(self, value: str) -> datetime | None:
        """Parse publish timestamps from API or RSS sources into UTC-aware datetimes."""
        if not value:
            return None
        cleaned = value.strip()
        try:
            if cleaned.endswith("Z"):
                cleaned = cleaned[:-1] + "+00:00"
            return self._ensure_aware_utc(datetime.fromisoformat(cleaned))
        except ValueError:
            pass
        for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
            try:
                return self._ensure_aware_utc(datetime.strptime(value, fmt))
            except ValueError:
                continue
        return None

    def _parse_iso_datetime(self, value: str) -> datetime | None:
        """Parse an ISO datetime string into a UTC-aware datetime."""
        if not value:
            return None
        try:
            return self._ensure_aware_utc(datetime.fromisoformat(value))
        except ValueError:
            return None

    def _ensure_aware_utc(self, value: datetime) -> datetime:
        """Normalize any datetime into a timezone-aware UTC value."""
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _news_timeframe_label(self, request: UserRequest) -> str:
        """Build the human-readable news date window shown in the email."""
        since_dt = self._parse_iso_datetime(request.since)
        until_dt = self._parse_iso_datetime(request.until)
        if not since_dt or not until_dt:
            return "Date range unavailable."
        return (
            f"{since_dt.astimezone(ZoneInfo('Australia/Sydney')).strftime('%B %d, %Y')} "
            "to "
            f"{until_dt.astimezone(ZoneInfo('Australia/Sydney')).strftime('%B %d, %Y')}."
        )

    async def _load_digest_metadata(self) -> dict:
        """Read optional rotation metadata from disk if it exists."""
        try:
            exists = await asyncio.to_thread(METADATA_PATH.exists)
            if exists:
                raw = await asyncio.to_thread(METADATA_PATH.read_text, encoding="utf-8")
                payload = json.loads(raw)
                if isinstance(payload, dict):
                    return payload
        except Exception as exc:
            logger.warning("Unable to read digest metadata: %s", exc)
        return {}

    async def _load_last_digest_timestamp(self) -> str:
        """Read just the last send time from the stored metadata payload."""
        payload = await self._load_digest_metadata()
        return str(payload.get("last_sent_at", "") or "")

    async def _save_digest_metadata(
        self,
        last_sent_at: str,
        last_photo_keys: list[str] | None = None,
        last_webcam_links: list[str] | None = None,
    ) -> None:
        """Persist send time and rotation metadata for later runs."""
        try:
            existing = await self._load_digest_metadata()
            await asyncio.to_thread(METADATA_PATH.parent.mkdir, parents=True, exist_ok=True)
            payload = {**existing, "last_sent_at": last_sent_at}
            if last_photo_keys is not None:
                payload["last_photo_keys"] = last_photo_keys
                payload["photo_rotation_offset"] = int(existing.get("photo_rotation_offset", 0) or 0) + 3
            if last_webcam_links is not None:
                payload["last_webcam_links"] = last_webcam_links
            await asyncio.to_thread(METADATA_PATH.write_text, json.dumps(payload), encoding="utf-8")
        except Exception as exc:
            logger.warning("Unable to write digest metadata: %s", exc)

    # Small template helpers
    def _season_background(self, hemisphere: str, month: str) -> str:
        """Map month and hemisphere to the background color used in the email."""
        month_lookup = {
            "january": 1,
            "february": 2,
            "march": 3,
            "april": 4,
            "may": 5,
            "june": 6,
            "july": 7,
            "august": 8,
            "september": 9,
            "october": 10,
            "november": 11,
            "december": 12,
        }
        month_num = month_lookup.get((month or "").strip().lower(), datetime.now(ZoneInfo("Australia/Sydney")).month)
        is_southern = (hemisphere or "").strip().lower() == "southern"
        if month_num in {12, 1, 2}:
            season = "summer" if is_southern else "winter"
        elif month_num in {3, 4, 5}:
            season = "autumn" if is_southern else "spring"
        elif month_num in {6, 7, 8}:
            season = "winter" if is_southern else "summer"
        else:
            season = "spring" if is_southern else "autumn"
        return {
            "spring": "#dff7df",
            "summer": "#fff7cc",
            "autumn": "#f3d28a",
            "winter": "#dfefff",
        }[season]
