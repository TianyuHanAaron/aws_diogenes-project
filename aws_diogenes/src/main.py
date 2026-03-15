#!/usr/bin/env python

"""Flow entrypoints for collecting inputs, rendering, sending, and saving digests."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from crewai.flow import Flow, and_, listen, or_, router, start

from models import DigestInputs, DigestResult, FlowState
from services.digest_pipeline import DigestPipelineService


APP_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = Path("/tmp") if os.getenv("AWS_LAMBDA_FUNCTION_NAME") else Path.cwd()
CREWAI_STORAGE_DIR = APP_DIR / ".crewai_storage"
os.environ.setdefault("CREWAI_STORAGE_DIR", str(CREWAI_STORAGE_DIR))


class EmailsFlow(Flow[FlowState]):
    """Main digest flow following CrewAI Flow start/listen patterns."""

    pipeline = DigestPipelineService()

    def _mark_status(self, status: FlowState.model_fields["status"].annotation) -> None:
        """Update the current flow status in one place."""
        self.state.status = status

    def _record_delivery_failure(self, exc: Exception) -> str:
        """Store a delivery failure without aborting the whole flow."""
        self.state.delivered = False
        self.state.delivery_status = "failed"
        self.state.delivery_error = str(exc)
        self._mark_status("email_failed")
        return "email_failed"

    def _record_delivery_success(self) -> str:
        """Store a successful delivery result in one place."""
        self.state.delivered = True
        self.state.delivery_status = "sent"
        self.state.delivery_error = ""
        self._mark_status("email_sent")
        return "email_sent"

    @start()
    async def collect_inputs(self, crewai_trigger_payload: dict | None = None) -> DigestInputs:
        """Build the request and gather tool inputs for the digest."""
        print("Collecting input data")
        self.state.started_at = datetime.now(timezone.utc).isoformat()
        self._mark_status("collecting_inputs")
        self.state.request = await self.pipeline.build_request(crewai_trigger_payload)
        self.state.inputs = await self.pipeline.collect_inputs(self.state.request)
        self._mark_status("inputs_collected")
        print("Inputs collected")
        return self.state.inputs

    @listen(collect_inputs)
    async def generate_email_digest(self, _: DigestInputs) -> DigestResult:
        """Render the digest after all inputs have been collected."""
        print("Rendering email digest sections")
        self._mark_status("rendering_digest")
        self.state.digest = await self.pipeline.generate_digest(self.state.inputs)
        self._mark_status("digest_generated")
        print("Email digest generated")
        return self.state.digest

    @router(generate_email_digest)
    def route_delivery(self, _: DigestResult) -> str:
        """Choose whether the flow should deliver the email or skip delivery."""
        self._mark_status("routing_delivery")
        if not self.state.request.email:
            return "skip_email_delivery_branch"
        return "request_email_delivery"

    @listen("request_email_delivery")
    async def perform_email_delivery(self) -> str:
        """Send the rendered email when a recipient address is present."""
        print("Sending email")
        self._mark_status("delivering_email")
        try:
            await self.pipeline.deliver_digest(self.state.request, self.state.digest)
        except Exception as exc:
            return self._record_delivery_failure(exc)
        return self._record_delivery_success()

    @listen("skip_email_delivery_branch")
    def record_skipped_delivery(self) -> str:
        """Mark delivery as skipped when the request has no email address."""
        self.state.delivered = False
        self.state.delivery_status = "skipped"
        self._mark_status("email_skipped")
        return "email_skipped"

    @listen(or_(perform_email_delivery, record_skipped_delivery))
    async def save_email(self) -> str:
        """Persist the rendered digest after either delivery branch finishes."""
        print("Saving email digest")
        self._mark_status("saving_email")
        output_path = await self.pipeline.save_digest(self.state.digest, OUTPUT_DIR)
        self.state.output_path = str(output_path)
        self.state.saved = True
        self._mark_status("email_saved")
        print("Email saved")
        return "email_saved"

    @listen(or_(and_(perform_email_delivery, save_email), and_(record_skipped_delivery, save_email)))
    def finalize_email_flow(self) -> FlowState:
        """Finalize timestamps and return the completed flow state."""
        self.state.completed_at = datetime.now(timezone.utc).isoformat()
        self._mark_status("completed")
        return self.state


def _new_flow() -> EmailsFlow:
    """Create a fresh flow instance for each entrypoint call."""
    return EmailsFlow()


def kickoff_email_flow() -> FlowState:
    """Run the email flow with default inputs."""
    return _new_flow().kickoff()


def plot():
    """Render the flow graph."""
    return _new_flow().plot()


def run_email_flow(payload: dict) -> FlowState:
    """Run the email flow with a trigger payload."""
    return _new_flow().kickoff({"crewai_trigger_payload": payload})


def run_with_user_request(user_request: dict) -> FlowState:
    """Run the email flow for a direct user request payload."""
    return run_email_flow(user_request)


def run_with_trigger():
    """CLI entrypoint that accepts one JSON payload argument."""
    if len(sys.argv) < 2:
        raise ValueError("Provide JSON payload")

    try:
        payload = json.loads(sys.argv[1])
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid JSON payload") from exc

    return run_email_flow(payload)


if __name__ == "__main__":
    kickoff_email_flow()
