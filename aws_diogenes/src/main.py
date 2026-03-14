#!/usr/bin/env python

import os
from pathlib import Path

from pydantic import BaseModel, Field
from crewai.flow import Flow, listen, start

from models import DigestInputs, DigestResult, UserRequest
from services.digest_pipeline import DigestPipelineService


APP_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = Path("/tmp") if os.getenv("AWS_LAMBDA_FUNCTION_NAME") else Path.cwd()
CREWAI_STORAGE_DIR = APP_DIR / ".crewai_storage"
os.environ.setdefault("CREWAI_STORAGE_DIR", str(CREWAI_STORAGE_DIR))


class Messages(BaseModel):
    request: UserRequest = Field(default_factory=UserRequest)
    inputs: DigestInputs = Field(default_factory=DigestInputs)
    digest: DigestResult = Field(default_factory=DigestResult)


class MessagesFlow(Flow[Messages]):
    pipeline = DigestPipelineService()

    @start()
    def collect_inputs(self, crewai_trigger_payload: dict = None):

        print("Collecting input data")
        self.state.request = self.pipeline.build_request(crewai_trigger_payload)
        self.state.inputs = self.pipeline.collect_inputs(self.state.request)

        print("Inputs collected")

    @listen(collect_inputs)
    def generate_email_digest(self):

        print("Running curated email crew")
        self.state.digest = self.pipeline.generate_digest(self.state.inputs)

        print("Email digest generated")

    @listen(generate_email_digest)
    def deliver_email(self):

        print("Sending email")
        self.pipeline.deliver_digest(self.state.request, self.state.digest)

        print("Email delivered")

    @listen(deliver_email)
    def save_email(self):

        print("Saving email digest")
        self.pipeline.save_digest(self.state.digest, OUTPUT_DIR)

        print("Email saved")


def kickoff():

    flow = MessagesFlow()
    flow.kickoff()


def plot():

    flow = MessagesFlow()
    flow.plot()


def run_digest(payload: dict):

    flow = MessagesFlow()
    return flow.kickoff({"crewai_trigger_payload": payload})


def run_with_user_request(user_request: dict):

    return run_digest(user_request)


def run_with_trigger():

    import json
    import sys

    if len(sys.argv) < 2:
        raise Exception("Provide JSON payload")

    try:
        payload = json.loads(sys.argv[1])

    except json.JSONDecodeError:
        raise Exception("Invalid JSON payload")

    return run_digest(payload)


if __name__ == "__main__":
    kickoff()
