import sys
from pathlib import Path
from unittest.mock import patch


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from main import run_digest
from models import DigestInputs, DigestResult, UserRequest


def test_run_digest_smoke():
    payload = {
        "email": "",
        "location": "australia",
        "hemisphere": "southern",
        "channels": ["global", "interest"],
        "interests": ["astronomy", "ai"],
    }

    request = UserRequest.model_validate(payload)
    inputs = DigestInputs(request=request)

    with patch("main.MessagesFlow.pipeline.build_request", return_value=request), patch(
        "main.MessagesFlow.pipeline.collect_inputs", return_value=inputs
    ), patch(
        "main.MessagesFlow.pipeline.generate_digest", return_value=DigestResult(html="<html></html>")
    ), patch("main.MessagesFlow.pipeline.deliver_digest"), patch(
        "main.MessagesFlow.pipeline.save_digest"
    ):
        result = run_digest(payload)

    assert result is not None
