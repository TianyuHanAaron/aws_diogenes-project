import json
import random
from faker import Faker
from datetime import datetime

fake = Faker()

DATA_DIR = "data"


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

    for i in range(count):

        posts.append({
            "author": f"@{fake.user_name()}",
            "platform": random.choice(platforms),
            "content": fake.sentence(nb_words=12),
            "timestamp": fake.date_time_this_week().isoformat()
        })

    return posts


def generate_photos(count=15):

    photos = []

    categories = [
        "skyline",
        "sunset",
        "flower",
        "food",
        "street scene",
        "park",
        "animal"
    ]

    for i in range(count):

        photos.append({
            "photo_id": f"p{i}",
            "location": "Sydney",
            "category": random.choice(categories),
            "url": f"https://example.com/photo_{i}.jpg",
            "timestamp": fake.date_time_this_month().isoformat()
        })

    return photos


def generate_seasonal_events():

    events = [
        {
            "event": "Perseid Meteor Shower",
            "location": "Sydney",
            "date_range": "Aug 11–Aug 13",
            "description": "Meteor shower caused by debris from comet Swift–Tuttle."
        },
        {
            "event": "Jacaranda Blossom Season",
            "location": "Sydney",
            "date_range": "October",
            "description": "Jacaranda trees bloom across the city."
        },
        {
            "event": "Spring Bird Migration",
            "location": "Sydney",
            "date_range": "September",
            "description": "Many bird species migrate across the region."
        }
    ]

    return events


def generate_trusted_contacts():

    contacts = []

    for _ in range(5):

        contacts.append(f"@{fake.user_name()}")

    return {
        "trusted_accounts": contacts
    }


def generate_user_profile():

    return [{
        "user_id": "u001",
        "name": fake.name(),
        "email": fake.email(),
        "phone": fake.phone_number(),
        "location": "Sydney"
    }]


def generate_user_subscriptions():

    channels = ["GLOBAL", "LOCAL", "INVESTMENT", "INTEREST"]

    return {
        "user_id": "u001",
        "channels": random.sample(channels, 3),
        "interest_topics": [
            "astronomy",
            "archaeology",
            "natural science"
        ]
    }


def save_json(filename, data):

    with open(f"data/{filename}", "w") as f:
        json.dump(data, f, indent=2)


def main():

    save_json("mock_news.json", generate_news())
    save_json("mock_posts.json", generate_posts())
    save_json("mock_photos.json", generate_photos())
    save_json("mock_seasonal_events.json", generate_seasonal_events())
    save_json("trusted_contacts.json", generate_trusted_contacts())
    save_json("user_profiles.json", generate_user_profile())
    save_json("user_subscriptions.json", generate_user_subscriptions())

    print("Mock data generated successfully")


if __name__ == "__main__":
    main()