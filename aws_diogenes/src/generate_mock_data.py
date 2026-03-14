import json
import random
from pathlib import Path

from faker import Faker

fake = Faker()

DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_USER_ID = "demo_user"
DEFAULT_LOCATION = "user_city"


def generate_news(count=20):

    news = []

    topics = [
        "artificial intelligence",
        "astronomy",
        "archaeology",
        "economics",
        "international politics",
        "biotechnology",
        "climate science"
    ]

    for i in range(count):

        topic = random.choice(topics)

        news.append({
            "id": f"n{i}",
            "title": fake.sentence(nb_words=8),
            "content": fake.paragraph(nb_sentences=4),
            "source": fake.company(),
            "published_at": fake.date_time_this_month().isoformat(),
            "topic": topic
        })

    return news


def generate_photos(count=15):

    photos = []
    scenes = [
        "city waterfront at sunset",
        "local market street",
        "harbour shoreline in late afternoon",
        "park pathway after rain",
        "street cafe corner",
        "flowering trees near the station",
        "skyline seen from a bridge"
    ]
    locations = [DEFAULT_LOCATION, "sydney"]

    for i in range(count):
        scene = random.choice(scenes)

        photos.append({
            "photo_id": f"p{i}",
            "location": random.choice(locations),
            "scene": scene,
            "category": scene.split()[0],
            "url": f"https://example.com/photo_{i}.jpg",
            "timestamp": fake.date_time_this_month().isoformat()
        })

    return photos


def generate_seasonal_events():

    events = [
        {
            "event": "Perseid Meteor Shower",
            "location": DEFAULT_LOCATION,
            "date_range": "Aug 11–Aug 13",
            "description": "Meteor shower caused by debris from comet Swift–Tuttle."
        },
        {
            "event": "Jacaranda Blossom Season",
            "location": "sydney",
            "date_range": "October",
            "description": "Jacaranda trees bloom across the city."
        },
        {
            "event": "Spring Bird Migration",
            "location": "sydney",
            "date_range": "September",
            "description": "Many bird species migrate across the region."
        }
    ]

    return events


def generate_user_profile():

    return [{
        "user_id": DEFAULT_USER_ID,
        "name": fake.name(),
        "email": fake.email(),
        "phone": fake.phone_number(),
        "location": DEFAULT_LOCATION
    }]


def generate_user_subscriptions():

    channels = ["GLOBAL", "LOCAL", "INVESTMENT", "INTEREST"]

    return {
        "user_id": DEFAULT_USER_ID,
        "channels": random.sample(channels, 3),
        "interest_topics": [
            "astronomy",
            "archaeology",
            "natural science"
        ]
    }


def save_json(filename, data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with (DATA_DIR / filename).open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def main():
    save_json("mock_news.json", generate_news())
    save_json("mock_photos.json", generate_photos())
    save_json("mock_seasonal_events.json", generate_seasonal_events())
    save_json("user_profiles.json", generate_user_profile())
    save_json("user_subscriptions.json", generate_user_subscriptions())

    print("Mock data generated successfully")


if __name__ == "__main__":
    main()
