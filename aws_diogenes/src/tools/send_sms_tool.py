from crewai.tools import BaseTool
import os
from typing import Type

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel, Field


class SendSMSInput(BaseModel):
    phone_number: str = Field(..., description="Recipient phone number")
    message: str = Field(..., description="SMS message content")


class SendSMSTool(BaseTool):
    name: str = "send_sms"
    description: str = "Send SMS message using AWS SNS"
    args_schema: Type[BaseModel] = SendSMSInput

    def _run(self, phone_number: str, message: str) -> str:
        client_kwargs = {}
        aws_region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
        if aws_region:
            client_kwargs["region_name"] = aws_region

        sns = boto3.client("sns", **client_kwargs)

        try:
            sns.publish(
                PhoneNumber=phone_number,
                Message=message
            )
        except (BotoCoreError, ClientError) as exc:
            raise RuntimeError(f"SNS publish failed: {exc}") from exc

        return "SMS sent successfully"
