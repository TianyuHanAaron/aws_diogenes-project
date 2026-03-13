#!/usr/bin/env python

import os
from pathlib import Path

from pydantic import BaseModel, Field
from crewai.flow import Flow, listen, start

from crews.trust_posts.trust_posts import TrustPostsCrew
from crews.curated_emails.curated_emails import CuratedEmailsCrew

from tools.fetch_news_tool import FetchNewsTool
from tools.fetch_social_posts_tool import FetchSocialPostsTool
from tools.fetch_seasonal_events_tool import FetchSeasonalEventsTool
from tools.fetch_local_photos_tool import FetchLocalPhotosTool


APP_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = Path.cwd()
CREWAI_STORAGE_DIR = APP_DIR / ".crewai_storage"
os.environ.setdefault("CREWAI_STORAGE_DIR", str(CREWAI_STORAGE_DIR))


class Messages(BaseModel):

    news: list = Field(default_factory=list)
    posts: list = Field(default_factory=list)
    trusted_contacts: list = Field(default_factory=list)
    trusted_posts_digest: str = ""
    seasonal_events: list = Field(default_factory=list)
    photos: list = Field(default_factory=list)

    curated_email: str = ""


class MessagesFlow(Flow[Messages]):

    @start()
    def collect_inputs(self, crewai_trigger_payload: dict = None):

        print("Collecting input data")

        fetch_news = FetchNewsTool()
        fetch_posts = FetchSocialPostsTool()
        fetch_events = FetchSeasonalEventsTool()
        fetch_photos = FetchLocalPhotosTool()

        location = "user_city"
        topic = "general news"
        user_id = "demo_user"
        trusted_contacts = []

        if crewai_trigger_payload:
            location = crewai_trigger_payload.get("location", location)
            topic = crewai_trigger_payload.get("topic", topic)
            user_id = crewai_trigger_payload.get("user_id", user_id)
            trusted_contacts = crewai_trigger_payload.get("trusted_contacts", trusted_contacts)

        try:
            self.state.news = fetch_news.run(topic=topic)
        except RuntimeError as exc:
            if "NEWSAPI_API_KEY is not set" in str(exc):
                print("NEWSAPI_API_KEY is not set; continuing with no news articles.")
                self.state.news = []
            else:
                raise
        self.state.posts = fetch_posts.run(user_id=user_id)
        self.state.trusted_contacts = trusted_contacts
        self.state.seasonal_events = fetch_events.run(location=location)
        self.state.photos = fetch_photos.run(location=location)

        print("Inputs collected")

    @listen(collect_inputs)
    def process_trusted_posts(self):

        print("Running trusted posts crew")

        result = TrustPostsCrew().crew().kickoff(
            inputs={
                "posts": self.state.posts,
                "trusted_contacts": self.state.trusted_contacts,
            }
        )

        self.state.trusted_posts_digest = getattr(result, "raw", str(result))

        print("Trusted posts processed")

    @listen(process_trusted_posts)
    def generate_email_digest(self):

        print("Running curated email crew")

        result = (
            CuratedEmailsCrew()
            .crew()
            .kickoff(
                inputs={
                    "news": self.state.news,
                    "seasonal_events": self.state.seasonal_events,
                    "photos": self.state.photos
                }
            )
        )

        self.state.curated_email = result.raw

        print("Email digest generated")

    @listen(generate_email_digest)
    def save_email(self):

        print("Saving email digest")

        with open(OUTPUT_DIR / "curated_email.html", "w") as f:
            f.write(self.state.curated_email)

        if self.state.trusted_posts_digest:
            with open(OUTPUT_DIR / "trusted_posts_digest.txt", "w") as f:
                f.write(self.state.trusted_posts_digest)

        print("Email saved")


def kickoff():

    flow = MessagesFlow()
    flow.kickoff()


def plot():

    flow = MessagesFlow()
    flow.plot()


def run_with_trigger():

    import json
    import sys

    if len(sys.argv) < 2:
        raise Exception("Provide JSON payload")

    try:
        payload = json.loads(sys.argv[1])
    except json.JSONDecodeError:
        raise Exception("Invalid JSON payload")

    flow = MessagesFlow()

    result = flow.kickoff(
        {"crewai_trigger_payload": payload}
    )

    return result


if __name__ == "__main__":
    kickoff()
