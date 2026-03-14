from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
import logging
import re
from zoneinfo import ZoneInfo

from crews.curated_emails.curated_emails import CuratedEmailsCrew
from models import CityLandmark, DigestInputs, DigestResult, NewsItem, PhotoCandidate, SeasonalEventResult, UserRequest
from services.email_sender import send_digest_email
from tools.fetch_city_landmarks_tool import FetchCityLandmarksTool
from tools.fetch_local_photos_tool import FetchLocalPhotosTool
from tools.fetch_news_tool import FetchNewsTool
from tools.fetch_seasonal_events_tool import FetchSeasonalEventsTool


logger = logging.getLogger(__name__)
TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "email_template.html"
STATE_DIR = Path("/tmp") if os.getenv("AWS_LAMBDA_FUNCTION_NAME") else Path.cwd()
METADATA_PATH = STATE_DIR / "last_digest_metadata.json"


class DigestPipelineService:
    def __init__(
        self,
        news_tool: FetchNewsTool | None = None,
        seasonal_events_tool: FetchSeasonalEventsTool | None = None,
        city_landmarks_tool: FetchCityLandmarksTool | None = None,
        photos_tool: FetchLocalPhotosTool | None = None,
        crew_factory=CuratedEmailsCrew,
    ):
        self.news_tool = news_tool or FetchNewsTool()
        self.seasonal_events_tool = seasonal_events_tool or FetchSeasonalEventsTool()
        self.city_landmarks_tool = city_landmarks_tool or FetchCityLandmarksTool()
        self.photos_tool = photos_tool or FetchLocalPhotosTool()
        self.crew_factory = crew_factory

    def build_request(self, payload: dict | None = None) -> UserRequest:
        payload = payload or {}
        request = UserRequest.model_validate(payload)
        now = datetime.now(ZoneInfo("Australia/Sydney"))
        if not request.month:
            request.month = now.strftime("%B")
        request.until = now.isoformat()
        if not request.since:
            request.since = self._load_last_digest_timestamp() or now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        return request

    def collect_inputs(self, request: UserRequest) -> DigestInputs:
        news: list[NewsItem]
        try:
            news = [
                NewsItem.from_raw(item)
                for item in self.news_tool.run(query=request.topic)
            ]
            news = self._filter_news_by_window(news, request)
        except RuntimeError as exc:
            if "NEWSAPI_API_KEY is not set" in str(exc):
                print("NEWSAPI_API_KEY not set; continuing without news")
                news = []
            else:
                raise

        try:
            seasonal_events = [
                SeasonalEventResult.from_raw(item)
                for item in self.seasonal_events_tool.run(
                    location=request.location,
                    hemisphere=request.hemisphere,
                    month=request.month,
                )
            ]
        except Exception as exc:
            logger.warning("Seasonal event collection failed: %s", exc)
            seasonal_events = []
        try:
            camera_data = self.city_landmarks_tool.run(location=request.location)
            landmarks = [
                CityLandmark.from_raw(item)
                for item in camera_data.get("landmarks", [])
            ]
        except Exception as exc:
            logger.warning("City landmarks collection failed: %s", exc)
            landmarks = []
        photos = [
            PhotoCandidate.from_raw(item, fallback_location=request.location)
            for item in self.photos_tool.run(location=request.location)
        ]

        return DigestInputs(
            request=request,
            news=news,
            seasonal_events=seasonal_events,
            landmarks=landmarks,
            photos=photos,
        )

    def generate_digest(self, inputs: DigestInputs) -> DigestResult:
        result = (
            self.crew_factory()
            .crew()
            .kickoff(
                inputs={
                    "news": [item.model_dump() for item in inputs.news],
                    "seasonal_events": [item.model_dump() for item in inputs.seasonal_events],
                    "landmarks": [item.model_dump() for item in inputs.landmarks],
                    "photos": [item.model_dump() for item in inputs.photos],
                    "location": inputs.request.location,
                    "hemisphere": inputs.request.hemisphere,
                    "month": inputs.request.month,
                    "interests": inputs.request.interests,
                    "channels": inputs.request.channels,
                }
            )
        )
        raw_output = getattr(result, "raw", str(result))
        html = self._render_html_digest(inputs, raw_output)
        return DigestResult(html=html, raw=raw_output)

    def deliver_digest(self, request: UserRequest, digest: DigestResult) -> None:
        if not request.email:
            return
        send_digest_email(
            receiver_email=request.email,
            subject="Daily Knowledge Digest",
            body=digest.html,
        )
        self._save_last_digest_timestamp(request.until or datetime.now(ZoneInfo("Australia/Sydney")).isoformat())

    def save_digest(self, digest: DigestResult, output_dir: Path) -> Path:
        output_path = output_dir / "curated_email.html"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(digest.html, encoding="utf-8")
        return output_path

    def _render_html_digest(self, inputs: DigestInputs, raw_output: str) -> str:
        template = TEMPLATE_PATH.read_text(encoding="utf-8")

        title = f"{inputs.request.location} Knowledge Digest"
        rendered = template
        rendered = rendered.replace("{{title}}", escape(title))
        rendered = rendered.replace(
            "{{season_background}}",
            self._season_background(inputs.request.hemisphere, inputs.request.month),
        )
        rendered = rendered.replace(
            "{{date}}",
            escape(datetime.now(ZoneInfo("Australia/Sydney")).strftime("%B %d, %Y")),
        )
        rendered = rendered.replace(
            "{{seasonal_events}}",
            self._render_seasonal_events(inputs.seasonal_events),
        )
        rendered = rendered.replace(
            "{{live_city_landmarks}}",
            self._render_live_city_landmarks(inputs.landmarks, inputs.photos, inputs.request.location),
        )
        rendered = rendered.replace(
            "{{news_sections}}",
            self._render_news_sections(inputs.news, inputs.request),
        )
        rendered = rendered.replace(
            "{{photos}}",
            self._render_photos(inputs.photos, inputs.request.location),
        )
        return rendered

    def _clean_llm_output(self, raw_output: str) -> str:
        text = raw_output.strip()
        fenced = re.search(r"```html\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
        if fenced:
            text = fenced.group(1).strip()
        if text.lower().startswith("<html"):
            return text

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        filtered: list[str] = []
        for line in lines:
            lower = line.lower()
            if lower.startswith("i need to "):
                continue
            if lower.startswith("i have assembled "):
                continue
            if lower.startswith("the next step would be "):
                continue
            if lower.startswith("however, since "):
                continue
            filtered.append(line)
        return "\n".join(filtered)

    def _render_seasonal_events(self, events: list[SeasonalEventResult]) -> str:
        if not events:
            return '<div class="event">No seasonal events were available for this run.</div>'

        blocks = []
        seen: set[str] = set()
        for item in events:
            extracted = self._extract_event_summary(item)
            if not extracted:
                continue
            title, summary = extracted
            dedupe_key = f"{title}|{summary}".lower()
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            blocks.append(
                '<div class="event">'
                '<span class="badge">Seasonal</span>'
                f'<strong>{escape(title)}</strong><br>'
                f'{escape(summary)}'
                "</div>"
            )
            if len(blocks) >= 4:
                break
        if not blocks:
            return '<div class="event">No readable seasonal events were available for this run.</div>'
        return "".join(blocks)

    def _render_news_sections(self, news_items: list[NewsItem], request: UserRequest) -> str:
        selected = {channel.lower() for channel in request.channels}
        buckets: dict[str, list[NewsItem]] = {
            "global": [],
            "local": [],
            "investment": [],
            "interest": [],
        }

        for item in news_items:
            channel = self._classify_news_item(item)
            buckets[channel].append(item)

        labels = {
            "global": "Global",
            "local": "Local",
            "investment": "Investment",
            "interest": "Interest",
        }
        sections: list[str] = []
        timeframe_note = (
            '<div class="news-description" style="margin-bottom:18px;">'
            f'{escape(self._news_timeframe_label(request))}'
            "</div>"
        )
        per_section_target = self._balanced_section_target(selected)
        for name, items in buckets.items():
            if name not in selected:
                continue
            candidates = self._channel_candidates(items, request, name, target=per_section_target + 2)
            rewritten = self._rewrite_news_batch(candidates, request, name)
            rendered_items: list[str] = []
            for item in candidates:
                rendered_item = self._render_news_item(item, request, name, rewritten.get(id(item)))
                if rendered_item:
                    rendered_items.append(rendered_item)
                if len(rendered_items) >= per_section_target:
                    break
            if not rendered_items:
                sections.append(
                    '<div class="news-group">'
                    f'<div class="news-group-title">{labels[name]}</div>'
                    '<div class="news-description">'
                    "No qualifying developments were available for this section."
                    "</div>"
                    "</div>"
                )
                continue
            sections.append(
                '<div class="news-group">'
                f'<div class="news-group-title">{labels[name]}</div>'
                f'{"".join(rendered_items)}'
                "</div>"
            )
        if not sections:
            return '<div class="news-description">No news sections were selected for this digest.</div>'
        return timeframe_note + "".join(sections)

    def _render_live_city_landmarks(
        self,
        landmarks: list[CityLandmark],
        photos: list[PhotoCandidate],
        location: str,
    ) -> str:
        if not landmarks:
            return (
                '<div class="news-description">'
                f'No live landmark snapshots were available for {escape(location)} during this run.'
                "</div>"
            )
        ranked_photos = sorted(
            photos,
            key=lambda photo: self._photo_priority(photo, location),
            reverse=True,
        )
        cells = []
        for index, landmark in enumerate(landmarks[:3]):
            fallback_photo_url = ""
            if index < len(ranked_photos):
                fallback_photo_url = self._best_photo_url(ranked_photos[index])
            image_url = landmark.image if self._is_probable_image_url(landmark.image) else fallback_photo_url
            image_html = ""
            if self._is_probable_image_url(landmark.image):
                image_html = (
                    f'<a href="{escape(landmark.stream or landmark.image)}" target="_blank" rel="noopener noreferrer">'
                    f'<img src="{escape(landmark.image)}" alt="" '
                    'style="width:100%;height:auto;display:block;border:0;" />'
                    "</a>"
                )
            elif self._is_probable_image_url(image_url):
                image_html = (
                    f'<a href="{escape(landmark.stream or image_url)}" target="_blank" rel="noopener noreferrer">'
                    f'<img src="{escape(image_url)}" alt="" '
                    'style="width:100%;height:auto;display:block;border:0;" />'
                    "</a>"
                )
            cells.append(
                '<td class="landmark-cell" style="width:33.33%;vertical-align:top;padding-right:10px;">'
                '<div class="landmark-card" style="border-radius:8px;overflow:hidden;background:#fafafa;border:1px solid #eee;">'
                f"{image_html}"
                f'<div class="landmark-name">{escape(landmark.name)}</div>'
                f'<div class="landmark-link"><a href="{escape(landmark.stream or image_url or landmark.image)}" '
                'target="_blank" rel="noopener noreferrer">View live</a></div>'
                "</div></td>"
            )
        return (
            '<div class="news-description" style="margin-bottom:14px;">'
            "Each image is a live snapshot representing the current city atmosphere when the digest was generated."
            "</div>"
            '<table class="landmark-table" role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" '
            'style="width:100%;border-collapse:collapse;"><tr>'
            f'{"".join(cells)}'
            "</tr></table>"
        )

    def _render_news_item(
        self,
        item: NewsItem,
        request: UserRequest,
        channel: str,
        rewritten: tuple[str, str] | None = None,
    ) -> str:
        normalized = rewritten or self._normalize_news_item(item, request, channel)
        if not normalized:
            return ""
        _, summary = normalized
        return (
            '<div class="news-item">'
            f'<div class="news-description">{escape(summary or "No summary available.")}</div>'
            "</div>"
        )

    def _classify_news_item(self, item: NewsItem) -> str:
        text = " ".join(
            [
                item.title or "",
                item.summary or "",
                item.source or "",
            ]
        ).lower()
        local_keywords = ["sydney", "australia", "australian", "nsw", "new south wales"]
        interest_keywords = ["art", "architecture", "film", "culture", "museum", "cinema", "design"]

        if any(keyword in text for keyword in local_keywords):
            return "local"
        if self._is_investment_news(item):
            return "investment"
        if any(keyword in text for keyword in interest_keywords):
            return "interest"
        return "global"

    def _render_photos(self, photos: list[PhotoCandidate], location: str) -> str:
        cards = []
        ranked_photos = sorted(
            photos,
            key=lambda photo: self._photo_priority(photo, location),
            reverse=True,
        )
        for index, photo in enumerate(ranked_photos[:10]):
            caption = self._photo_caption(photo, location, index)
            image_url = self._best_photo_url(photo)
            if not self._is_probable_image_url(image_url):
                cards.append(
                    "<tr><td style=\"padding:0 0 16px 0;\">"
                    '<div class="photo-card" style="border-radius:8px;overflow:hidden;background:#fafafa;border:1px solid #eee;">'
                    f'<div class="caption">{escape(caption)}</div>'
                    "</div></td></tr>"
                )
                continue
            cards.append(
                "<tr><td style=\"padding:0 0 16px 0;\">"
                '<div class="photo-card" style="border-radius:8px;overflow:hidden;background:#fafafa;border:1px solid #eee;">'
                f'<a href="{escape(image_url)}" target="_blank" rel="noopener noreferrer" '
                'style="text-decoration:none;color:inherit;display:block;">'
                f'<img src="{escape(image_url)}" alt="{escape(caption)}" '
                'style="width:100%;height:auto;display:block;border:0;outline:none;text-decoration:none;" />'
                '</a>'
                f'<div class="caption">{escape(caption)}<br>'
                f'<a href="{escape(image_url)}" target="_blank" rel="noopener noreferrer">View image</a></div>'
                "</div></td></tr>"
            )
        if not cards:
            return '<div class="caption">No local photographs were available for this run.</div>'
        return "".join(cards)

    def _photo_priority(self, photo: PhotoCandidate, location: str) -> int:
        raw = photo.raw or {}
        text = " ".join(
            [
                photo.location or "",
                photo.photographer or "",
                str(raw.get("alt") or ""),
                str(raw.get("description") or ""),
                str(raw.get("photographer") or ""),
                str(raw.get("user", {}).get("name") if isinstance(raw.get("user"), dict) else ""),
            ]
        ).lower()
        location_terms = self._location_terms(location)

        score = 0
        landmark_terms = [
            "opera house", "harbour bridge", "bridge", "harbour", "harbor",
            "skyline", "waterfront", "ferry", "cbd", "downtown", "city centre",
            "city center", "street", "urban", "night", "nightscape", "sunset",
            "sunrise", "evening", "lights", "illuminated", "aerial", "panoramic",
            "landmark", "tower", "square", "station", "boulevard",
        ]
        weak_terms = [
            "portrait", "person", "selfie", "food", "dish", "plate", "flower",
            "pet", "animal", "macro", "close-up", "close up", "studio", "product",
            "wedding", "fashion", "model",
        ]

        for term in landmark_terms:
            if term in text:
                score += 4
        for term in weak_terms:
            if term in text:
                score -= 5
        for term in location_terms:
            if term and term in text:
                score += 3
        if self._is_probable_image_url(self._best_photo_url(photo)):
            score += 2
        if photo.source in {"pexels", "unsplash", "pixabay"}:
            score += 1
        return score

    def _photo_caption(self, photo: PhotoCandidate, location: str, index: int) -> str:
        raw = photo.raw or {}
        candidates = [
            raw.get("alt"),
            raw.get("description"),
            raw.get("photographer"),
            raw.get("user", {}).get("name") if isinstance(raw.get("user"), dict) else None,
        ]
        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return f"Local street scene from {location} ({index + 1})."

    def _best_photo_url(self, photo: PhotoCandidate) -> str:
        raw = photo.raw or {}
        candidates = [
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
        ]
        for candidate in candidates:
            value = str(candidate or "").strip()
            if self._is_probable_image_url(value):
                return value
        return ""

    def _is_probable_image_url(self, url: str) -> bool:
        value = (url or "").strip()
        if not value.startswith("http"):
            return False
        image_hosts = [
            "images.pexels.com",
            "images.unsplash.com",
            "cdn.pixabay.com",
            "pixabay.com/get/",
        ]
        if any(host in value for host in image_hosts):
            return True
        if re.search(r"\.(jpg|jpeg|png|webp)(?:\?|$)", value, flags=re.IGNORECASE):
            return True
        return False

    def _normalize_news_item(self, item: NewsItem, request: UserRequest, channel: str) -> tuple[str, str] | None:
        if not self._is_relevant_to_request(item, request, channel):
            return None
        if not self._is_event_driven_news(item):
            return None
        title = self._plain_title(item.title, item.summary)
        summary = self._plain_summary(item.summary, request, channel)
        if not title:
            return None
        if self._is_emotionally_loaded(title):
            return None
        if self._is_emotionally_loaded(summary):
            summary = self._strip_loaded_sentences(summary)
        if self._is_emotionally_loaded(summary):
            return None
        if not summary:
            summary = "Summary omitted because the source text did not meet the digest's neutral-tone policy."
        if len(title) < 6:
            return None
        return title, summary

    def _rewrite_news_batch(
        self,
        items: list[NewsItem],
        request: UserRequest,
        channel: str,
    ) -> dict[int, tuple[str, str]]:
        if not items:
            return {}
        try:
            from nova_model import nova_lite
        except Exception as exc:
            logger.warning("Nova rewrite unavailable; falling back to deterministic rendering: %s", exc)
            return {}

        prompt_items = []
        for index, item in enumerate(items, start=1):
            prompt_items.append(
                {
                    "id": index,
                    "source": item.source,
                    "title": item.title,
                    "summary": item.summary,
                    "published": item.published,
                }
            )
        prompt = (
            "You are rewriting news items for a calm knowledge digest.\n"
            "Task: extract the underlying fact, development, or idea from each item and restate it in plain language.\n"
            "Rules:\n"
            "- Keep the tone dry, factual, and emotionally flat.\n"
            "- Do not preserve rhetorical framing, outrage framing, personal drama, or promotional wording.\n"
            "- Shorten the title to at most 6 words.\n"
            "- Write a complete plain-language summary in 3-5 sentences when enough source information is available.\n"
            "- Include the main development, the relevant context, and the practical consequence or significance when those details are present.\n"
            "- Do not cut the explanation halfway through; prefer completeness over brevity.\n"
            "- Use only information present in the item.\n"
            "- If the item is mostly opinion, marketing, vague human-interest framing, or lacks a clear factual point, mark drop=true.\n"
            f"- User topic: {request.topic}\n"
            f"- Channel: {channel}\n"
            f"- User interests: {', '.join(request.interests) if request.interests else 'none'}\n"
            "Return only valid JSON in this exact shape:\n"
            '[{"id":1,"title":"...","summary":"...","drop":false}]\n'
            f"Items:\n{json.dumps(prompt_items, ensure_ascii=True)}"
        )

        try:
            response = nova_lite.call(prompt)
            parsed = self._parse_rewrite_response(response)
        except Exception as exc:
            logger.warning("Nova rewrite failed; falling back to deterministic rendering: %s", exc)
            return {}

        by_id: dict[int, tuple[str, str]] = {}
        for entry in parsed:
            try:
                item_id = int(entry.get("id"))
            except Exception:
                continue
            if entry.get("drop"):
                continue
            title = self._neutralize_title(str(entry.get("title", "")))
            summary = self._neutralize_summary(str(entry.get("summary", "")))
            summary = self._strip_loaded_sentences(summary)
            if not title:
                continue
            if self._is_emotionally_loaded(title) or self._is_emotionally_loaded(summary):
                continue
            by_id[item_id] = (title[:80].strip(), self._first_plain_sentences(summary, limit=5, max_chars=900))

        results: dict[int, tuple[str, str]] = {}
        for index, item in enumerate(items, start=1):
            if index in by_id:
                results[id(item)] = by_id[index]
        return results

    def _parse_rewrite_response(self, response: object) -> list[dict]:
        text = str(response).strip()
        fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
        if fenced:
            text = fenced.group(1).strip()
        if not text.startswith("["):
            match = re.search(r"(\[\s*\{.*\}\s*\])", text, flags=re.DOTALL)
            if match:
                text = match.group(1)
        data = json.loads(text)
        return data if isinstance(data, list) else []

    def _extract_event_summary(self, item: SeasonalEventResult) -> tuple[str, str] | None:
        content = item.content if isinstance(item.content, list) else []
        for entry in content:
            if not isinstance(entry, dict):
                continue
            raw_title = self._sanitize_event_text(str(entry.get("title") or ""))
            summary = self._sanitize_event_text(
                str(entry.get("description") or entry.get("snippet") or entry.get("markdown") or "")
            )
            title = self._event_friendly_title(item.query, raw_title)
            if self._looks_like_event_noise(title) and self._looks_like_event_noise(summary):
                continue
            if self._mentions_wrong_year(summary):
                continue
            if not self._is_specific_event_title(item.query, raw_title, title):
                continue
            if not title:
                title = self._event_title_from_query(item.query)
            if not summary or self._looks_like_truncated_text(summary):
                summary = self._event_summary_from_query(item.query, title)
            else:
                summary = self._first_plain_sentences(summary, limit=5, max_chars=900)
            if self._should_skip_generic_location_event(item.query, title, summary):
                continue
            if not summary or self._looks_like_event_noise(summary):
                continue
            return title, summary
        fallback_title = self._event_title_from_query(item.query)
        fallback_summary = self._event_summary_from_query(item.query, fallback_title)
        if fallback_summary and self._is_specific_event_title(item.query, "", fallback_title):
            return fallback_title, fallback_summary
        return None

    def _sanitize_event_text(self, text: str) -> str:
        value = text or ""
        value = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", value)
        value = re.sub(r"#+\s*", "", value)
        value = re.sub(r"https?://\S+", "", value)
        value = re.sub(r"\bselect all\b.*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\bshowing:\s*\d+.*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\bfor:\s*\d.*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s+", " ", value).strip(" -–—|")
        return value

    def _looks_like_event_noise(self, text: str) -> bool:
        value = (text or "").strip().lower()
        if not value:
            return True
        noisy_fragments = [
            "suggested searches",
            "select all",
            "public holidays and non-working days",
            "upcoming holidays",
            "holidays and observances",
            "view all topics",
            "showing:",
            "for: 2000",
            "search",
        ]
        return any(fragment in value for fragment in noisy_fragments)

    def _event_title_from_query(self, query: str) -> str:
        value = query.strip()
        replacements = {
            "site:timeanddate.com": "",
            "site:nasa.gov": "",
            "site:amsmeteors.org": "",
        }
        for old, new in replacements.items():
            value = value.replace(old, new)
        value = re.sub(r"\s+", " ", value).strip()
        value = value.title()
        return value[:80].strip()

    def _event_friendly_title(self, query: str, extracted_title: str) -> str:
        lowered_title = (extracted_title or "").lower()
        if not extracted_title or any(
            fragment in lowered_title
            for fragment in [
                "festivals march",
                "holidays march",
                "today's and upcoming holidays",
                "skywatching tips",
                "meteor shower calendar",
                "what's up:",
                "time and date",
                "nasa science",
            ]
        ):
            return self._event_title_from_query(query)
        return extracted_title

    def _is_specific_event_title(self, query: str, raw_title: str, final_title: str) -> bool:
        title = (final_title or "").strip()
        raw = (raw_title or "").strip()
        lowered_title = title.lower()
        lowered_query = query.lower()
        if not title:
            return False

        generic_titles = [
            "festivals march",
            "holidays march",
            "upcoming holidays",
            "today's and upcoming holidays",
            "holidays and observances",
            "skywatching tips",
            "meteor shower calendar",
            "current seasonal conditions",
            "seasonal observances",
            "skywatching highlights",
            "meteor activity",
        ]
        if any(fragment in lowered_title for fragment in generic_titles):
            return False

        if title == self._event_title_from_query(query):
            if any(term in lowered_query for term in ["festival", "festivals", "holiday", "holidays", "events"]):
                return False

        query_location = query.split()[0].lower() if query else ""
        title_words = [word for word in re.findall(r"[a-zA-Z']+", lowered_title) if len(word) > 2]
        if raw == "" and all(word in {query_location, "march", "april", "may", "june", "july", "august", "september", "october", "november", "december", "january", "february"} for word in title_words):
            return False

        return True

    def _event_summary_from_query(self, query: str, title: str = "") -> str:
        lowered = query.lower()
        location_name = query.split()[0].title() if query else "the selected city"
        if "meteor shower" in lowered:
            return (
                f"{title or 'Meteor activity'} is part of the current month skywatching calendar. "
                "This period can include stronger night-sky visibility, notable peak viewing dates, "
                "and observation conditions that matter for readers planning outdoor viewing."
            )
        if "skywatching" in lowered:
            return (
                f"{title or 'Skywatching highlights'} covers notable celestial events visible this month, "
                "including major alignments, eclipse activity, or bright-planet viewing windows. "
                "It is relevant as a practical guide to what can be observed in the night sky over the coming days."
            )
        if "festival" in lowered or "holidays" in lowered:
            return (
                f"{title or 'Seasonal observances'} refers to a current holiday or public celebration relevant to "
                f"{location_name}. It matters because it shapes local activity, cultural observance, and the rhythm "
                "of public events during this part of the month."
            )
        if "blossom" in lowered or "flower bloom" in lowered:
            return (
                f"{title or 'Bloom season'} marks the part of the year when seasonal flowering becomes visible in "
                f"{location_name}. It is relevant to local conditions because bloom timing reflects temperature, "
                "rainfall, and the current stage of the seasonal cycle."
            )
        if "bird migration" in lowered:
            return (
                f"{title or 'Bird migration activity'} reflects the current movement of species commonly observed in "
                f"{location_name}. It is relevant as an ecological signal of seasonal change and can affect what "
                "residents and visitors are likely to observe in parks, waterways, and coastal areas."
            )
        return (
            f"{title or 'Current seasonal conditions'} is a seasonal development relevant to {location_name}. "
            "It provides context about the city's current cultural calendar, ecological cycle, or skywatching conditions."
        )

    def _looks_like_truncated_text(self, text: str) -> bool:
        value = (text or "").strip()
        return value.endswith("...") or value.endswith("…") or "..." in value or "…" in value

    def _mentions_wrong_year(self, text: str) -> bool:
        years = re.findall(r"\b(20\d{2})\b", text or "")
        if not years:
            return False
        current_year = datetime.now(ZoneInfo("Australia/Sydney")).year
        return all(int(year) != current_year for year in years)

    def _should_skip_generic_location_event(self, query: str, title: str, summary: str) -> bool:
        lowered_query = query.lower()
        lowered_title = (title or "").lower()
        lowered_summary = (summary or "").lower()
        if "festival" in lowered_query or "holiday" in lowered_query or "events" in lowered_query:
            generic_markers = [
                "upcoming holidays",
                "holidays and observances",
                "public holiday",
                "national holiday",
                "seasonal observances",
                "festivals march",
                "holidays march",
            ]
            if any(marker in lowered_title for marker in generic_markers):
                return True
            if any(marker in lowered_summary for marker in generic_markers):
                return True
        return False

    def _plain_title(self, title: str, summary: str) -> str:
        value = self._neutralize_title(title)
        if not value:
            value = self._title_from_summary(summary)
        value = re.sub(r"\b(is leaving her role as|says|warns|reveals|slams|blasts)\b.*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\bthe\b", "the", value)
        words = value.split()
        if len(words) > 8:
            value = " ".join(words[:8])
        return value.strip(" -–—:;,.")

    def _plain_summary(self, summary: str, request: UserRequest, channel: str) -> str:
        value = self._neutralize_summary(summary)
        value = self._strip_loaded_sentences(value)
        value = self._select_relevant_sentences(value, request, channel)
        if not value:
            return ""
        value = self._first_plain_sentences(value, limit=5, max_chars=900)
        return value

    def _title_from_summary(self, summary: str) -> str:
        sentence = re.split(r"(?<=[.!?])\s+", (summary or "").strip(), maxsplit=1)[0]
        sentence = re.sub(r"^[^A-Za-z0-9]+", "", sentence)
        sentence = sentence.strip(" -–—")
        return sentence[:80].rstrip(" .")

    def _is_relevant_to_request(self, item: NewsItem, request: UserRequest, channel: str) -> bool:
        text = " ".join([item.title or "", item.summary or "", item.source or ""]).lower()
        topic_terms = [term for term in re.findall(r"[a-zA-Z]{4,}", request.topic.lower()) if term not in {"news", "general"}]
        interest_terms = [term.lower() for term in request.interests]
        location_terms = self._location_terms(request.location)
        if channel == "local":
            return any(keyword in text for keyword in location_terms)
        if channel == "interest":
            if interest_terms and any(term in text for term in interest_terms):
                return True
            return any(keyword in text for keyword in ["art", "architecture", "film", "culture", "museum", "cinema", "design"])
        if channel == "investment":
            return self._is_investment_news(item)
        if channel == "global":
            if not self._is_global_hard_news(item):
                return False
            if topic_terms:
                return any(term in text for term in topic_terms) or self._matches_global_topic_family(topic_terms)
            return True
        if topic_terms:
            return any(term in text for term in topic_terms)
        return True

    def _select_relevant_sentences(self, text: str, request: UserRequest, channel: str) -> str:
        if not text:
            return ""
        topic_terms = [term for term in re.findall(r"[a-zA-Z]{4,}", request.topic.lower()) if term not in {"news", "general"}]
        interest_terms = [term.lower() for term in request.interests]
        location_terms = self._location_terms(request.location)
        channel_terms = {
            "local": location_terms,
            "interest": interest_terms or ["art", "architecture", "film", "culture", "museum", "cinema", "design"],
            "investment": [
                "stock", "stocks", "market", "markets", "investment", "earnings", "fund",
                "inflation", "bond", "bonds", "rates", "interest rate", "central bank",
                "treasury", "revenue", "profit", "oil", "gas", "commodity", "commodities",
                "currency", "bank", "banking", "shares", "yield", "trade",
            ],
            "global": topic_terms,
        }.get(channel, [])
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        kept: list[str] = []
        for sentence in sentences:
            candidate = sentence.strip()
            if not candidate:
                continue
            lower = candidate.lower()
            if channel_terms and not any(term in lower for term in channel_terms):
                continue
            kept.append(candidate)
        return " ".join(kept).strip() or text.strip()

    def _channel_candidates(
        self,
        items: list[NewsItem],
        request: UserRequest,
        channel: str,
        target: int,
    ) -> list[NewsItem]:
        strict = [
            item for item in items
            if self._is_relevant_to_request(item, request, channel) and self._is_event_driven_news(item)
        ]
        if len(strict) >= target:
            return strict[:target]

        relaxed_event = [
            item for item in items
            if self._is_relevant_to_request(item, request, channel) and item not in strict
        ]
        combined = strict + relaxed_event
        if len(combined) >= target:
            return combined[:target]

        if channel == "global":
            broadened = [
                item for item in items
                if self._is_global_hard_news(item) and item not in combined
            ]
            combined.extend(broadened)
        if channel == "investment":
            broadened = [
                item for item in items
                if self._is_investment_news(item) and item not in combined
            ]
            combined.extend(broadened)
        return combined[:target]

    def _balanced_section_target(self, selected: set[str]) -> int:
        count = max(len(selected), 1)
        if count == 1:
            return 5
        if count == 2:
            return 4
        return 3

    def _first_plain_sentences(self, text: str, limit: int, max_chars: int) -> str:
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        kept: list[str] = []
        for sentence in sentences:
            candidate = sentence.strip()
            if not candidate:
                continue
            kept.append(candidate)
            if len(kept) >= limit:
                break
        value = " ".join(kept).strip()
        if len(value) > max_chars:
            shortened = value[:max_chars]
            boundary = max(shortened.rfind(". "), shortened.rfind("; "), shortened.rfind(": "))
            if boundary > 80:
                value = shortened[: boundary + 1].strip()
            else:
                value = shortened.rsplit(" ", 1)[0].rstrip(" ,;:") + "."
        if value and value[-1] not in ".!?":
            value += "."
        return value

    def _location_terms(self, location: str) -> list[str]:
        location_key = (location or "").strip().lower()
        terms = [part for part in re.split(r"[\s,/-]+", location_key) if len(part) > 2]
        aliases = {
            "sydney": ["sydney", "nsw", "new south wales"],
            "melbourne": ["melbourne", "victoria", "vic"],
            "brisbane": ["brisbane", "queensland", "qld"],
            "perth": ["perth", "western australia", "wa"],
            "adelaide": ["adelaide", "south australia", "sa"],
        }
        if location_key in aliases:
            return aliases[location_key]
        return terms or [location_key]

    def _is_event_driven_news(self, item: NewsItem) -> bool:
        text = " ".join([item.title or "", item.summary or ""]).lower()
        if re.search(r"\b(i|we|my|our)\b", item.title or "", flags=re.IGNORECASE):
            return False
        low_signal_patterns = [
            r"\b(opinion|newsletter|podcast|interview|conversation with)\b",
            r"\bwhy\b",
            r"\bhow\b",
            r"\bwhat .* means\b",
            r"\bsays\b",
            r"\btells\b",
            r"\bcritics\b",
            r"\bregret\b",
            r"\bcareer\b",
            r"\bmoved from\b",
            r"\bquit his job\b",
            r"\bchat show\b",
        ]
        if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in low_signal_patterns):
            return False
        event_patterns = [
            r"\b(announced|planned|approved|launched|opened|closed|signed|passed|reported|showed|released|published|won|lost)\b",
            r"\b(report|study|survey|data|policy|bill|budget|deal|festival|parade|exhibition|opening|release|election|court|strike|protest|flood|fire|storm|support|costs|prices|rate|inflation)\b",
        ]
        return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in event_patterns)

    def _is_investment_news(self, item: NewsItem) -> bool:
        text = " ".join([item.title or "", item.summary or "", item.source or ""]).lower()
        investment_patterns = [
            r"\bstock(s)?\b",
            r"\bmarket(s)?\b",
            r"\bbond(s)?\b",
            r"\betf(s)?\b",
            r"\bcrypto\b",
            r"\bbitcoin\b",
            r"\bshares?\b",
            r"\binvest(?:ment|or|ing)?\b",
            r"\bearnings\b",
            r"\brevenue\b",
            r"\bprofit(s)?\b",
            r"\bfund(s)?\b",
            r"\binflation\b",
            r"\binterest rate(s)?\b",
            r"\bcentral bank\b",
            r"\btreasury\b",
            r"\byield(s)?\b",
            r"\bcurrency\b",
            r"\bforeign exchange\b",
            r"\boil\b",
            r"\bgas\b",
            r"\bcommodity\b",
            r"\bcommodities\b",
            r"\bbank(s|ing)?\b",
            r"\btrade\b",
            r"\btariff(s)?\b",
        ]
        return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in investment_patterns)

    def _is_global_hard_news(self, item: NewsItem) -> bool:
        text = " ".join([item.title or "", item.summary or "", item.source or ""]).lower()
        positive_patterns = [
            r"\bgovernment\b",
            r"\bparliament\b",
            r"\bcongress\b",
            r"\bpresident\b",
            r"\bprime minister\b",
            r"\bministry\b",
            r"\bpolicy\b",
            r"\bbill\b",
            r"\bsanctions?\b",
            r"\bceasefire\b",
            r"\bconflict\b",
            r"\bmilitary\b",
            r"\bdefen[cs]e\b",
            r"\bsecurity\b",
            r"\bnato\b",
            r"\bunited nations\b",
            r"\bdiplomatic\b",
            r"\btrade\b",
            r"\btariffs?\b",
            r"\beconomy\b",
            r"\beconomic\b",
            r"\binflation\b",
            r"\binterest rates?\b",
            r"\bcentral bank\b",
            r"\bbudget\b",
            r"\bjobs\b",
            r"\bunemployment\b",
            r"\bgdp\b",
            r"\btechnology\b",
            r"\bai\b",
            r"\bsemiconductor\b",
            r"\bchip(s)?\b",
            r"\bcyber\b",
            r"\bdata centre\b",
            r"\btelecom\b",
            r"\benergy\b",
            r"\bhousing\b",
            r"\bhealth system\b",
            r"\beducation system\b",
            r"\bmigration\b",
            r"\bpopulation\b",
            r"\bcost of living\b",
            r"\bstrike\b",
            r"\bprotest\b",
            r"\belection\b",
            r"\bcourt\b",
            r"\bregulator\b",
            r"\bregulation\b",
        ]
        negative_patterns = [
            r"\bfashion\b",
            r"\bstyle\b",
            r"\bcelebrity\b",
            r"\bchat show\b",
            r"\bmovie star\b",
            r"\bactor\b",
            r"\bsinger\b",
            r"\bentertainment\b",
            r"\bred carpet\b",
            r"\blifestyle\b",
            r"\brestaurant\b",
            r"\btravel tips?\b",
            r"\bbody dissatisfaction\b",
            r"\bmothers?\b",
            r"\bregret\b",
            r"\bcorporate culture\b",
            r"\bside hustle\b",
            r"\bcalendar\b",
            r"\bholiday shopping\b",
            r"\bart week\b",
            r"\bzona maco\b",
        ]
        if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in negative_patterns):
            return False
        return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in positive_patterns)

    def _matches_global_topic_family(self, topic_terms: list[str]) -> bool:
        hard_news_topic_families = {
            "geopolitical": {"war", "security", "defense", "military", "diplomatic", "sanctions", "conflict", "election", "government", "politics"},
            "economic": {"economy", "economic", "inflation", "rates", "interest", "budget", "trade", "tariff", "gdp", "jobs", "market"},
            "technological": {"technology", "tech", "ai", "artificial", "semiconductor", "chip", "cyber", "telecom", "data"},
            "socioeconomic": {"housing", "migration", "population", "education", "health", "labour", "labor", "cost", "wages"},
        }
        term_set = set(topic_terms)
        return any(term_set & family_terms for family_terms in hard_news_topic_families.values())

    def _filter_news_by_window(self, news: list[NewsItem], request: UserRequest) -> list[NewsItem]:
        since_dt = self._parse_iso_datetime(request.since)
        until_dt = self._parse_iso_datetime(request.until)
        if not since_dt or not until_dt:
            return news
        filtered = self._news_in_range(news, since_dt, until_dt)
        if filtered:
            return filtered

        month_start = until_dt.astimezone(ZoneInfo("Australia/Sydney")).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        ).astimezone(timezone.utc)
        filtered = self._news_in_range(news, month_start, until_dt)
        if filtered:
            return filtered

        week_start = until_dt - timedelta(days=7)
        filtered = self._news_in_range(news, week_start, until_dt)
        return filtered or news

    def _news_in_range(self, news: list[NewsItem], since_dt: datetime, until_dt: datetime) -> list[NewsItem]:
        filtered: list[NewsItem] = []
        for item in news:
            published_dt = self._parse_published_datetime(item.published)
            if not published_dt:
                filtered.append(item)
                continue
            if since_dt <= published_dt <= until_dt:
                filtered.append(item)
        return filtered

    def _parse_published_datetime(self, value: str) -> datetime | None:
        if not value:
            return None
        cleaned = value.strip()
        try:
            if cleaned.endswith("Z"):
                cleaned = cleaned[:-1] + "+00:00"
            parsed = datetime.fromisoformat(cleaned)
            return self._ensure_aware_utc(parsed)
        except ValueError:
            pass
        for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
            try:
                parsed = datetime.strptime(value, fmt)
                return self._ensure_aware_utc(parsed)
            except ValueError:
                continue
        return None

    def _parse_iso_datetime(self, value: str) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
            return self._ensure_aware_utc(parsed)
        except ValueError:
            return None

    def _ensure_aware_utc(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _news_timeframe_label(self, request: UserRequest) -> str:
        since_dt = self._parse_iso_datetime(request.since)
        until_dt = self._parse_iso_datetime(request.until)
        if not since_dt or not until_dt:
            return "Coverage window unavailable."
        return (
            "Coverage window: "
            f"{since_dt.astimezone(ZoneInfo('Australia/Sydney')).strftime('%B %d, %Y')} "
            "to "
            f"{until_dt.astimezone(ZoneInfo('Australia/Sydney')).strftime('%B %d, %Y')}."
        )

    def _load_last_digest_timestamp(self) -> str:
        try:
            if METADATA_PATH.exists():
                payload = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
                return str(payload.get("last_sent_at", "") or "")
        except Exception as exc:
            logger.warning("Unable to read digest metadata: %s", exc)
        return ""

    def _save_last_digest_timestamp(self, value: str) -> None:
        try:
            METADATA_PATH.parent.mkdir(parents=True, exist_ok=True)
            METADATA_PATH.write_text(json.dumps({"last_sent_at": value}), encoding="utf-8")
        except Exception as exc:
            logger.warning("Unable to write digest metadata: %s", exc)

    def _neutralize_title(self, title: str) -> str:
        value = (title or "").strip()
        value = re.sub(r"^[\"'`]+|[\"'`]+$", "", value)
        value = re.sub(r"^(hello and welcome to|welcome to)\s+", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\b(newsletter|podcast|opinion|analysis|subscriber[s]?|exclusive)\b", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s*[|:-]\s*(newsletter|analysis|opinion|live|updates?)\b.*$", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s+", " ", value).strip(" -–—")
        value = value.rstrip("!?")
        if self._looks_like_marketing_copy(value):
            return ""
        return value

    def _neutralize_summary(self, summary: str) -> str:
        value = (summary or "").strip()
        value = re.sub(r"If this was forwarded to you.*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"can I interest you.*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"subscribe here.*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"read more.*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"click here.*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"sign up.*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s+", " ", value).strip()
        return value

    def _looks_like_marketing_copy(self, text: str) -> bool:
        marketing_patterns = [
            r"\bnewsletter\b",
            r"\bsubscribe\b",
            r"\bwelcome\b",
            r"\bforwarded to you\b",
            r"\bsign up\b",
            r"\bfull-fledged\b",
            r"\bfor only\b",
        ]
        return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in marketing_patterns)

    def _is_emotionally_loaded(self, text: str) -> bool:
        value = (text or "").strip()
        if not value:
            return False
        strong_patterns = [
            r"\bculture wars?\b",
            r"\bMAGA\b",
            r"\bwar(s)?\b",
            r"\bshocking\b",
            r"\bdramatic\b",
            r"\bslammed\b",
            r"\bblast(ed|s)?\b",
            r"\bfurious\b",
            r"\boutrage\b",
            r"\bexplosive\b",
            r"\bpanic\b",
            r"\bchaos\b",
            r"\bdevastating\b",
            r"\bmassive\b",
            r"\bhuge\b",
            r"\bviral\b",
            r"\broast(?:ing|ed)?\b",
            r"\bquit his job\b",
            r"\bit's the end of\b",
            r"\bside hustle\b",
            r"\beverybody has potential\b",
            r"\bwelcome to\b",
            r"\bhello and welcome\b",
            r"\bcan I interest you\b",
        ]
        if any(re.search(pattern, value, flags=re.IGNORECASE) for pattern in strong_patterns):
            return True
        if "!" in value or "?" in value:
            return True
        if len(re.findall(r"\b[A-Z]{3,}\b", value)) >= 2:
            return True
        return False

    def _strip_loaded_sentences(self, text: str) -> str:
        cleaned_sentences: list[str] = []
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            if self._is_emotionally_loaded(sentence):
                continue
            cleaned_sentences.append(sentence)
        return " ".join(cleaned_sentences).strip()

    def _season_background(self, hemisphere: str, month: str) -> str:
        month_to_season = {
            "northern": {
                "december": "winter",
                "january": "winter",
                "february": "winter",
                "march": "spring",
                "april": "spring",
                "may": "spring",
                "june": "summer",
                "july": "summer",
                "august": "summer",
                "september": "autumn",
                "october": "autumn",
                "november": "autumn",
            },
            "southern": {
                "december": "summer",
                "january": "summer",
                "february": "summer",
                "march": "autumn",
                "april": "autumn",
                "may": "autumn",
                "june": "winter",
                "july": "winter",
                "august": "winter",
                "september": "spring",
                "october": "spring",
                "november": "spring",
            },
        }
        season_colors = {
            "spring": "#dff7df",
            "summer": "#fff7cc",
            "autumn": "#f3d28a",
            "winter": "#dfefff",
        }
        hemisphere_key = hemisphere.lower().strip() if hemisphere else "northern"
        month_key = month.lower().strip() if month else ""
        season = month_to_season.get(hemisphere_key, month_to_season["northern"]).get(month_key, "spring")
        return season_colors[season]
