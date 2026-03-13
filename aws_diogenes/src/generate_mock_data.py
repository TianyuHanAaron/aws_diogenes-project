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


def generate_posts(count=10):

    posts = []
    platforms = ["x", "facebook", "wechat"]
    trusted_authors = [f"@{fake.user_name()}" for _ in range(3)]
    other_authors = [f"@{fake.user_name()}" for _ in range(2)]

    for i in range(count):
        is_demo_user = i < count - 2
        user_id = DEFAULT_USER_ID if is_demo_user else f"user_{i}"
        trusted = is_demo_user and i < len(trusted_authors)
        author_pool = trusted_authors if trusted else other_authors

        posts.append({
            "post_id": f"post_{i}",
            "user_id": user_id,
            "trusted": trusted,
            "location": DEFAULT_LOCATION,
            "author": f"@{fake.user_name()}",
            "platform": random.choice(platforms),
            "content": fake.sentence(nb_words=12),
            "timestamp": fake.date_time_between(start_date="-7d", end_date="now").isoformat()
        })

        posts[-1]["author"] = random.choice(author_pool)

    return posts


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


def generate_trusted_contacts(posts):
    trusted_accounts = sorted({post["author"] for post in posts if post["trusted"]})
    return {
        "user_id": DEFAULT_USER_ID,
        "trusted_accounts": trusted_accounts
    }


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
    posts = generate_posts()

    save_json("mock_news.json", generate_news())
    save_json("mock_posts.json", posts)
    save_json("mock_photos.json", generate_photos())
    save_json("mock_seasonal_events.json", generate_seasonal_events())
    save_json("trusted_contacts.json", generate_trusted_contacts(posts))
    save_json("user_profiles.json", generate_user_profile())
    save_json("user_subscriptions.json", generate_user_subscriptions())

    print("Mock data generated successfully")


if __name__ == "__main__":
    main()
