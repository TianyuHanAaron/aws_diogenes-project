import asyncio
from crewai.tools import BaseTool
import os
from typing import Type

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel, Field


class SendEmailInput(BaseModel):
    to_email: str = Field(..., description="Recipient email address")
    subject: str = Field(..., description="Email subject")
    html_body: str = Field(..., description="HTML email body")


class SendEmailTool(BaseTool):
    name: str = "send_email"
    description: str = "Send email digest using AWS SES"
    args_schema: Type[BaseModel] = SendEmailInput

    def _run(self, to_email: str, subject: str, html_body: str) -> str:
        source_email = os.getenv("AWS_SES_SOURCE_EMAIL")
        if not source_email:
            raise RuntimeError("AWS_SES_SOURCE_EMAIL is not set")

        client_kwargs = {}
        aws_region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
        if aws_region:
            client_kwargs["region_name"] = aws_region

        ses = boto3.client("ses", **client_kwargs)

        try:
            ses.send_email(
                Source=source_email,
                Destination={"ToAddresses": [to_email]},
                Message={
                    "Subject": {"Data": subject},
                    "Body": {
                        "Html": {"Data": html_body}
                    }
                }
            )
        except (BotoCoreError, ClientError) as exc:
            raise RuntimeError(f"SES send failed: {exc}") from exc

        return "Email sent successfully"

    async def arun(self, to_email: str, subject: str, html_body: str) -> str:
        """Run the SES send without blocking the event loop."""
        return await asyncio.to_thread(
            self.run,
            to_email=to_email,
            subject=subject,
            html_body=html_body,
        )
