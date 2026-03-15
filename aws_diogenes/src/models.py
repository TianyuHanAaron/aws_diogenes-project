from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class UserRequest(BaseModel):
    location: str = "unknown"
    hemisphere: str = "northern"
    topic: str = "general news"
    email: str = ""
    interests: list[str] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=list)
    month: str = ""
    since: str = ""
    until: str = ""


class NewsItem(BaseModel):
    title: str = ""
    summary: str = ""
    body: str = ""
    url: str = ""
    source: str = ""
    published: str = ""

    @classmethod
    def from_raw(cls, item: dict[str, Any]) -> "NewsItem":
        return cls(
            title=str(item.get("title", "")),
            summary=str(item.get("summary", item.get("content", "")) or ""),
            body=str(item.get("body", item.get("content", item.get("summary", ""))) or ""),
            url=str(item.get("url", "") or ""),
            source=str(item.get("source", "") or ""),
            published=str(item.get("published", item.get("published_at", "")) or ""),
        )


class SeasonalEventResult(BaseModel):
    query: str = ""
    content: Any = ""

    @classmethod
    def from_raw(cls, item: dict[str, Any]) -> "SeasonalEventResult":
        return cls(
            query=str(item.get("query", "")),
            content=item.get("content", ""),
        )


class PhotoCandidate(BaseModel):
    photo_id: str = ""
    url: str = ""
    location: str = ""
    photographer: str = ""
    source: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_raw(cls, item: dict[str, Any], fallback_location: str) -> "PhotoCandidate":
        photo_id = item.get("photo_id") or item.get("id") or item.get("uuid") or ""
        url = (
            item.get("src", {}).get("large")
            or item.get("src", {}).get("original")
            or item.get("urls", {}).get("regular")
            or item.get("urls", {}).get("small")
            or item.get("largeImageURL")
            or item.get("webformatURL")
            or item.get("url")
            or ""
        )
        photographer = (
            item.get("photographer")
            or item.get("user")
            or item.get("user", {}).get("name")
            or ""
        )
        source = "unknown"
        if "src" in item:
            source = "pexels"
        elif "urls" in item:
            source = "unsplash"
        elif "largeImageURL" in item or "webformatURL" in item:
            source = "pixabay"

        return cls(
            photo_id=str(photo_id),
            url=str(url),
            location=str(item.get("location", fallback_location) or fallback_location),
            photographer=str(photographer),
            source=source,
            raw=item,
        )


class CityLandmark(BaseModel):
    name: str = ""
    image: str = ""
    stream: str = ""

    @classmethod
    def from_raw(cls, item: dict[str, Any]) -> "CityLandmark":
        return cls(
            name=str(item.get("name", "") or ""),
            image=str(item.get("image", "") or ""),
            stream=str(item.get("stream", "") or ""),
        )


class DigestInputs(BaseModel):
    request: UserRequest = Field(default_factory=UserRequest)
    news: list[NewsItem] = Field(default_factory=list)
    seasonal_events: list[SeasonalEventResult] = Field(default_factory=list)
    photos: list[PhotoCandidate] = Field(default_factory=list)
    landmarks: list[CityLandmark] = Field(default_factory=list)


class DigestResult(BaseModel):
    html: str = ""
    raw: str = ""
    photo_keys: list[str] = Field(default_factory=list)
    webcam_links: list[str] = Field(default_factory=list)


class FlowState(BaseModel):
    """Typed state shared across the digest flow lifecycle."""

    request: UserRequest = Field(default_factory=UserRequest)
    inputs: DigestInputs = Field(default_factory=DigestInputs)
    digest: DigestResult = Field(default_factory=DigestResult)
    output_path: str | None = None
    delivered: bool = False
    saved: bool = False
    delivery_status: Literal["pending", "sent", "skipped", "failed"] = "pending"
    delivery_error: str = ""
    started_at: str = ""
    completed_at: str = ""
    status: Literal[
        "initialized",
        "collecting_inputs",
        "inputs_collected",
        "rendering_digest",
        "digest_generated",
        "routing_delivery",
        "delivering_email",
        "email_sent",
        "email_failed",
        "email_skipped",
        "saving_email",
        "email_saved",
        "completed",
    ] = "initialized"
