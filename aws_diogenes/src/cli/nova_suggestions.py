"""Nova-powered suggestions for initial news channel choices."""

from __future__ import annotations

import asyncio
import boto3
import json
import logging


logger = logging.getLogger(__name__)

CHANNEL_ALIASES = {
    "global": "global",
    "local": "local",
    "investment": "investment",
    "investing": "investment",
    "finance": "investment",
    "financial": "investment",
    "interest": "interest",
    "interests": "interest",
    "interested topic": "interest",
    "interested topics": "interest",
    "topic": "interest",
    "topics": "interest",
}


def _normalize_channels(raw_channels: object) -> list[str]:
    """Map model output into the canonical channel ids used by the backend."""
    if not isinstance(raw_channels, list):
        return []

    normalized: list[str] = []
    for item in raw_channels:
        key = str(item).strip().lower()
        value = CHANNEL_ALIASES.get(key)
        if value and value not in normalized:
            normalized.append(value)
    return normalized


def suggests_channels(interests: list[str]) -> list[str]:

    prompt = f"""
    A user has following interests:
    
    {', '.join(interests)}
    Available News Channels:
    - global
    - local
    - investment
    - interest
    
    Select the most relevant channels for the user,
    return a JSON list only.
    Use only the exact lowercase ids above.
    """

    body = {
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 300
    }

    try:
        client = boto3.client("bedrock-runtime")
        response = client.invoke_model(
            modelId="amazon.nova-lite-v1:0",
            body=json.dumps(body),
            contentType="application/json",
            accept="application/json",
        )
        result = json.loads(response["body"].read())
        text = result["output"]["message"]["content"][0]["text"]
        channels = json.loads(text)
        return _normalize_channels(channels) or ["interest"]
    except Exception as exc:
        logger.warning("Nova channel suggestion failed: %s", exc)
        return ["interest"]


async def suggests_channels_async(interests: list[str]) -> list[str]:
    """Suggest channels without blocking the event loop."""
    return await asyncio.to_thread(suggests_channels, interests)
