import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from lambda_handler import handler


def test_lambda_handler_uses_event_payload():
    event = {
        "location": "brisbane",
        "hemisphere": "southern",
        "topic": "astronomy",
        "channels": ["interest"],
        "interests": ["space"],
        "email": "user@example.com",
    }
    context = SimpleNamespace(aws_request_id="req-123")

    with patch("main.run_email_flow") as run_email_flow:
        response = handler(event, context)

    run_email_flow.assert_called_once_with(event)
    body = json.loads(response["body"])
    assert response["statusCode"] == 200
    assert body["ok"] is True
    assert body["request_id"] == "req-123"
