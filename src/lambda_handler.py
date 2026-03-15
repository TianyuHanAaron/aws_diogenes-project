"""AWS Lambda entrypoint for the scheduled digest."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path


# Keep CrewAI state inside Lambda's writable temp directory.
os.environ["HOME"] = "/tmp"
os.environ["CREWAI_DISABLE_TELEMETRY"] = "true"
os.environ["CREWAI_DISABLE_TRACING"] = "true"
os.environ["CREWAI_STORAGE_DIR"] = "/tmp/crewai"
os.environ["CREWAI_DB_PATH"] = "/tmp/crewai/db"
Path("/tmp/crewai/db").mkdir(parents=True, exist_ok=True)

logger = logging.getLogger(__name__)


def _default_payload() -> dict:
    """Build a default request from Lambda environment variables."""
    channels = os.getenv("DEFAULT_CHANNELS", "global,interest")
    interests = os.getenv("DEFAULT_INTERESTS", "")
    return {
        "location": os.getenv("DEFAULT_LOCATION", "sydney"),
        "hemisphere": os.getenv("DEFAULT_HEMISPHERE", "southern"),
        "topic": os.getenv("DEFAULT_TOPIC", "general news"),
        "email": os.getenv("DEFAULT_EMAIL", ""),
        "channels": [item.strip() for item in channels.split(",") if item.strip()],
        "interests": [item.strip() for item in interests.split(",") if item.strip()],
    }


def handler(event, context):
    """Merge the incoming event into the default payload and run the digest."""
    from main import run_email_flow

    payload = _default_payload()
    if isinstance(event, dict):
        payload.update({key: value for key, value in event.items() if value is not None})

    logger.info("Running scheduled digest", extra={"payload": payload})
    run_email_flow(payload)

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "ok": True,
                "request_id": getattr(context, "aws_request_id", None),
                "payload": payload,
            }
        ),
    }
