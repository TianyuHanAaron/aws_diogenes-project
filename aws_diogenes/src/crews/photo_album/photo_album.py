"""YAML-driven helpers for the city photograph album section."""

from __future__ import annotations

import re
from html import escape
from pathlib import Path

from crews.runtime_utils import (
    build_task_prompt,
    call_nova_text_async,
    extract_json,
    load_yaml_async,
)


CONFIG_DIR = Path(__file__).resolve().parent / "config"


async def generate_photo_album(photo_inputs: list[dict], location: str, last_photo_keys: list[str]) -> tuple[str, list[str]]:
    """Run the staged photo prompts and return rendered album HTML."""
    print("Photograph album: selecting city scenes...")
    agents, tasks = await load_yaml_async(CONFIG_DIR / "agents.yaml"), await load_yaml_async(CONFIG_DIR / "tasks.yaml")
    values = {"location": location}

    selection = await _run_json_stage(
        agents["photo_scene_selector_agent"],
        tasks["photo_scene_selection_task"],
        values,
        {"photos": photo_inputs, "last_photo_keys": last_photo_keys},
    )
    print("Photograph album: writing captions...")
    captioned = await _run_json_stage(
        agents["photo_caption_editor_agent"],
        tasks["photo_scene_caption_task"],
        values,
        {"selected_photos": selection},
    )
    print("Photograph album: reviewing album selection...")
    reviewed = await _run_json_stage(
        agents["photo_album_review_agent"],
        tasks["photo_album_review_task"],
        values,
        {
            "captioned_photos": captioned,
            "selected_photos": selection,
            "photos": photo_inputs,
            "last_photo_keys": last_photo_keys,
        },
    )

    reviewed_items = _normalize_photo_items(reviewed)
    if not reviewed_items:
        reviewed_items = _normalize_photo_items(_selection_with_default_captions(selection))

    payload = await _run_json_stage(
        agents["photo_album_layout_agent"],
        tasks["photo_album_layout_task"],
        values,
        {"captioned_photos": reviewed_items},
    )

    if not isinstance(payload, dict):
        return _build_photo_album_rows(reviewed_items), [item["photo_key"] for item in reviewed_items]

    html = str(payload.get("html", "") or "").strip()
    photo_keys = payload.get("photo_keys") if isinstance(payload.get("photo_keys"), list) else []
    normalized_keys = [str(key) for key in photo_keys if str(key)]
    if _has_valid_rendered_images(html):
        print("Photograph album: done")
        return html, normalized_keys or [item["photo_key"] for item in reviewed_items]
    print("Photograph album: using safe fallback layout")
    return _build_photo_album_rows(reviewed_items), normalized_keys or [item["photo_key"] for item in reviewed_items]


async def _run_json_stage(agent_config: dict, task_config: dict, values: dict, payloads: dict) -> dict | list:
    """Render one YAML-defined photo stage and decode its JSON response."""
    prompt = build_task_prompt(agent_config, task_config, values, payloads)
    payload = extract_json(await call_nova_text_async(prompt))
    if isinstance(payload, (dict, list)):
        return payload
    return {} if "JSON object" in str(task_config.get("expected_output", "")) else []


def _normalize_photo_items(payload: list | dict) -> list[dict]:
    """Normalize captions and remove any item without a usable image URL."""
    items = payload if isinstance(payload, list) else []
    normalized: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        image_url = str(item.get("image_url", "") or "").strip()
        if not _is_usable_image_url(image_url):
            continue

        caption = re.sub(r"[{}\"]", "", str(item.get("caption", "") or "").strip())
        caption = re.sub(r"\s+", " ", caption).strip()
        if len(caption.split()) > 10:
            caption = " ".join(caption.split()[:10]).rstrip(" ,;:.") + "."

        normalized.append(
            {
                "photo_key": str(item.get("photo_key", "") or ""),
                "image_url": image_url,
                "caption": caption or "City scene.",
            }
        )
    return normalized


def _selection_with_default_captions(payload: list | dict) -> list[dict]:
    """Build a safe caption fallback from the selected image metadata."""
    items = payload if isinstance(payload, list) else []
    fallback: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        fallback.append(
            {
                "photo_key": item.get("photo_key", ""),
                "image_url": item.get("image_url", ""),
                "caption": _default_caption_from_text(str(item.get("source_text", "") or "")),
            }
        )
    return fallback


def _has_valid_rendered_images(html: str) -> bool:
    """Make sure the agent returned actual image tags instead of placeholders."""
    if not html or "<img" not in html.lower():
        return False
    image_sources = re.findall(r'<img[^>]+src="([^"]+)"', html, flags=re.IGNORECASE)
    text_content = re.sub(r"<[^>]+>", " ", html)
    text_content = re.sub(r"\s+", " ", text_content).strip()
    return any(_is_usable_image_url(src) for src in image_sources) and len(text_content) >= 12


def _is_usable_image_url(url: str) -> bool:
    """Accept only direct https image URLs for email rendering."""
    lowered = url.lower()
    return lowered.startswith("https://") and " " not in lowered and "javascript:" not in lowered


def _build_photo_album_rows(items: list[dict]) -> str:
    """Render a deterministic photo album fallback when the model layout is bad."""
    rows: list[str] = []
    for item in items[:10]:
        rows.append(
            '<tr><td style="padding:0 0 16px 0;">'
            '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" '
            'style="width:100%;border-collapse:collapse;background:#fafafa;border:1px solid #eeeeee;'
            'border-radius:8px;overflow:hidden;">'
            '<tr><td>'
            f'<img src="{escape(item["image_url"])}" alt="{escape(item["caption"])}" '
            'style="display:block;width:100%;height:auto;border:0;outline:none;text-decoration:none;">'
            '</td></tr>'
            '<tr><td style="padding:10px 12px;font-size:13px;line-height:1.5;color:#4b5563;">'
            f'{escape(item["caption"])}'
            "</td></tr>"
            "</table>"
            "</td></tr>"
        )
    return "".join(rows)


def _default_caption_from_text(text: str) -> str:
    """Generate a short factual fallback caption from source metadata."""
    cleaned = re.sub(r"[{}\"]", "", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return "City scene."
    words = cleaned.split()
    if len(words) > 10:
        cleaned = " ".join(words[:10]).rstrip(" ,;:.") + "."
    return cleaned
