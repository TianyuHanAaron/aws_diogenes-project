import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from services.email_sender import send_digest_email


def test_send_digest_email_sends_html_and_text_parts():
    ses_client = MagicMock()
    ses_client.send_email.return_value = {"MessageId": "123"}

    with patch.dict(
        "os.environ",
        {
            "AWS_DEFAULT_REGION": "ap-southeast-2",
            "SES_SENDER_EMAIL": "sender@example.com",
        },
        clear=False,
    ), patch("services.email_sender.boto3.client", return_value=ses_client):
        send_digest_email(
            receiver_email="to@example.com",
            subject="Digest",
            body="<h1>Hello</h1><p>World</p>",
        )

    kwargs = ses_client.send_email.call_args.kwargs
    assert kwargs["Message"]["Body"]["Html"]["Data"] == "<h1>Hello</h1><p>World</p>"
    assert kwargs["Message"]["Body"]["Text"]["Data"] == "Hello World"
