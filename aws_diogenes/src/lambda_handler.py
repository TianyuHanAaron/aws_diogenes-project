import os
import pathlib
import json
import logging

# Force writable home directory
os.environ["HOME"] = "/tmp"

# Disable CrewAI telemetry and tracing
os.environ["CREWAI_DISABLE_TELEMETRY"] = "true"
os.environ["CREWAI_DISABLE_TRACING"] = "true"

# Redirect CrewAI storage
os.environ["CREWAI_STORAGE_DIR"] = "/tmp/crewai"
os.environ["CREWAI_DB_PATH"] = "/tmp/crewai/db"

# Ensure directories exist
pathlib.Path("/tmp/crewai/db").mkdir(parents=True, exist_ok=True)

logger = logging.getLogger(__name__)


def _default_payload():
    channels = os.getenv("DEFAULT_CHANNELS", "global,interest")
    interests = os.getenv("DEFAULT_INTERESTS", "")

    return {
        "location": os.getenv("DEFAULT_LOCATION", "sydney"),
        "hemisphere": os.getenv("DEFAULT_HEMISPHERE", "southern"),
        "topic": os.getenv("DEFAULT_TOPIC", "general news"),
        "email": os.getenv("DEFAULT_EMAIL", ""),
        "channels": [c.strip() for c in channels.split(",") if c.strip()],
        "interests": [i.strip() for i in interests.split(",") if i.strip()],
    }


def handler(event, context):

    # Lazy import to reduce cold start
    from main import run_digest

    payload = _default_payload()

    if isinstance(event, dict):
        payload.update({k: v for k, v in event.items() if v is not None})

    logger.info("Running scheduled digest", extra={"payload": payload})

    run_digest(payload)

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