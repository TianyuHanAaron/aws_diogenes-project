"""Helpers for loading and saving CLI user profiles."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path


DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "user_profiles.json"


def load_profiles() -> list[dict]:
    """Return all saved user profiles."""
    if not DATA_PATH.exists():
        return []
    with DATA_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


async def load_profiles_async() -> list[dict]:
    """Return all saved user profiles without blocking the event loop."""
    return await asyncio.to_thread(load_profiles)


def save_profiles(profiles: list[dict]) -> None:
    """Persist the provided user profiles."""
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DATA_PATH.open("w", encoding="utf-8") as handle:
        json.dump(profiles, handle, indent=2)


async def save_profiles_async(profiles: list[dict]) -> None:
    """Persist user profiles without blocking the event loop."""
    await asyncio.to_thread(save_profiles, profiles)


def find_user(user_id: str) -> dict | None:
    """Look up one user profile by id."""
    return next((profile for profile in load_profiles() if profile.get("user_id") == user_id), None)


async def find_user_async(user_id: str) -> dict | None:
    """Look up one user profile by id without blocking the event loop."""
    return await asyncio.to_thread(find_user, user_id)
