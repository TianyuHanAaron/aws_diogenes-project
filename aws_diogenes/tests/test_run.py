import sys
from pathlib import Path
from unittest.mock import patch


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from main import run_email_flow
from models import DigestInputs, DigestResult, UserRequest


def test_run_email_flow_smoke():
    payload = {
        "email": "",
        "location": "australia",
        "hemisphere": "southern",
        "channels": ["global", "interest"],
        "interests": ["astronomy", "ai"],
    }

    request = UserRequest.model_validate(payload)
    inputs = DigestInputs(request=request)

    with patch("main.EmailsFlow.pipeline.build_request", return_value=request), patch(
        "main.EmailsFlow.pipeline.collect_inputs", return_value=inputs
    ), patch(
        "main.EmailsFlow.pipeline.generate_digest", return_value=DigestResult(html="<html></html>")
    ), patch("main.EmailsFlow.pipeline.deliver_digest"), patch(
        "main.EmailsFlow.pipeline.save_digest"
    ):
        result = run_email_flow(payload)

    assert result is not None
