"""Helpers for sending rendered digest emails through Amazon SES."""

import asyncio
import boto3
import os
import re


def _html_to_text(html_body: str) -> str:
    """Generate a plain-text fallback body from the rendered HTML email."""
    text = re.sub(r"<[^>]+>", " ", html_body)
    text = re.sub(r"\s+", " ", text).strip()
    return text or "Diogenes Sunlight Post"


def send_digest_email(receiver_email: str, subject: str, body: str):
    """Send one HTML digest email and include a plain-text alternative body."""
    ses_region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
    ses_sender = os.getenv("AWS_SES_SOURCE_EMAIL") or os.getenv("SES_SENDER_EMAIL")

    client_kwargs = {}
    if ses_region:
        client_kwargs["region_name"] = ses_region

    ses_client = boto3.client("ses", **client_kwargs)

    response = ses_client.send_email(
        Source=ses_sender,
        Destination={
            "ToAddresses": [receiver_email]
        },
        Message={
            "Subject": {
                "Data": subject,
                "Charset": "UTF-8"
            },
            "Body": {
                "Html": {
                    "Data": body,
                    "Charset": "UTF-8"
                },
                "Text": {
                    "Data": _html_to_text(body),
                    "Charset": "UTF-8"
                }
            }
        }
    )

    return response


async def send_digest_email_async(receiver_email: str, subject: str, body: str):
    """Send the digest email without blocking the event loop."""
    return await asyncio.to_thread(send_digest_email, receiver_email, subject, body)
