"""Interactive CLI for creating profiles and triggering digest runs."""

from __future__ import annotations

import asyncio
import re
from contextlib import suppress
from pathlib import Path

import questionary

try:
    from main import run_with_user_request
except ImportError:
    from ..main import run_with_user_request

from .profiles import find_user_async, load_profiles_async, save_profiles_async
from .menus import main_menu, channel_menu, frequency_menu
from .nova_suggestions import suggests_channels_async

with suppress(ImportError):
    from crewai.events.utils.console_formatter import set_suppress_console_output


CHANNEL_LABELS = {
    "global": "Global",
    "local": "Local",
    "investment": "Investment",
    "interest": "Interest",
}

CHANNEL_ALIASES = {
    "global": "global",
    "local": "local",
    "investment": "investment",
    "interest": "interest",
    "interests": "interest",
    "interested topic": "interest",
    "interested topics": "interest",
}
DEFAULT_CHANNELS = ["global", "interest"]

_LAST_USER_ID: str | None = None


def _run_async(coro):
    """Execute one async helper from the synchronous CLI layer."""
    return asyncio.run(coro)


def _save_user(updated_user: dict) -> None:
    """Persist one updated profile back into the local profile store."""
    profiles = _run_async(load_profiles_async())
    for index, profile in enumerate(profiles):
        if profile["user_id"] == updated_user["user_id"]:
            profiles[index] = updated_user
            _run_async(save_profiles_async(profiles))
            return
    profiles.append(updated_user)
    _run_async(save_profiles_async(profiles))


def _prompt_text(message: str, required: bool = True) -> str | None:
    """Read and normalize one text answer from questionary."""
    answer = questionary.text(message).ask()
    if answer is None:
        print("Prompt cancelled")
        return None
    value = answer.strip()
    if required and not value:
        print("A value is required")
        return None
    return value


def _prompt_user_id() -> str | None:
    """Request the target user id once for CLI actions."""
    return _prompt_text("User ID")


def _profile_label(profile: dict) -> str:
    """Build a readable menu label for one saved user profile."""
    user_id = profile.get("user_id", "unknown")
    location = profile.get("location", "unknown location")
    email = profile.get("email", "no-email")
    return f"{user_id} | {location} | {email}"


def _remember_user(user_id: str | None) -> None:
    """Track the last user touched during this CLI session."""
    global _LAST_USER_ID
    if user_id:
        _LAST_USER_ID = user_id


def _prompt_user(action: str) -> dict | None:
    """Select a saved user profile with minimal typing."""
    profiles = _run_async(load_profiles_async())

    if not profiles:
        user_id = _prompt_user_id()
        if not user_id:
            return None
        user = _run_async(find_user_async(user_id))
        if user:
            _remember_user(user.get("user_id"))
        return user

    ordered_profiles = profiles[:]
    if _LAST_USER_ID:
        ordered_profiles.sort(key=lambda profile: profile.get("user_id") != _LAST_USER_ID)

    if len(ordered_profiles) == 1:
        user = ordered_profiles[0]
        _remember_user(user.get("user_id"))
        print(f"Using saved user: {_profile_label(user)}")
        return user

    choices = [questionary.Choice(_profile_label(profile), value=profile) for profile in ordered_profiles]
    choices.append(questionary.Choice("Enter user ID manually", value="manual"))
    selected = questionary.select(f"Select a user for {action}", choices=choices).ask()
    if selected is None:
        print("Prompt cancelled")
        return None
    if selected == "manual":
        user_id = _prompt_user_id()
        if not user_id:
            return None
        user = _run_async(find_user_async(user_id))
        if user:
            _remember_user(user.get("user_id"))
        return user

    _remember_user(selected.get("user_id"))
    return selected


def _normalize_channels(channels: list[str] | None) -> list[str]:
    """Map menu or model output onto backend channel ids."""
    normalized: list[str] = []
    for item in channels or []:
        value = CHANNEL_ALIASES.get(str(item).strip().lower())
        if value and value not in normalized:
            normalized.append(value)
    return normalized


def _format_channels(channels: list[str]) -> str:
    """Create a human-readable summary of selected channels."""
    return ", ".join(CHANNEL_LABELS.get(channel, channel.title()) for channel in channels)


def _parse_interests(raw_interests: str) -> list[str]:
    """Split comma-separated interests into a clean unique list."""
    parsed: list[str] = []
    for item in raw_interests.split(","):
        value = item.strip()
        if value and value not in parsed:
            parsed.append(value)
    return parsed


def _extract_digest_preview(html_text: str) -> tuple[str, list[str]]:
    """Pull a short title and visible section headings from rendered email HTML."""
    title_match = re.search(r"<h1[^>]*>(.*?)</h1>", html_text, flags=re.IGNORECASE | re.DOTALL)
    heading_matches = re.findall(r"<h2[^>]*>(.*?)</h2>", html_text, flags=re.IGNORECASE | re.DOTALL)

    def _clean(fragment: str) -> str:
        text = re.sub(r"<[^>]+>", " ", fragment)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    title = _clean(title_match.group(1)) if title_match else "Diogenes Sunlight Post"
    headings = [_clean(item) for item in heading_matches]
    headings = [item for item in headings if item]
    return title, headings


def _print_local_digest_summary(output_path: str) -> None:
    """Show a small local summary so failed delivery still feels complete."""
    try:
        html_text = Path(output_path).read_text(encoding="utf-8")
    except OSError:
        return

    title, headings = _extract_digest_preview(html_text)
    print("Local digest preview")
    print(f"Title: {title}")
    if headings:
        print("Sections: " + " | ".join(headings))


def create_user() -> None:
    """Create and persist a new local user profile."""
    user_id = _prompt_user_id()
    email = _prompt_text("Email")
    location = _prompt_text("City")
    if not user_id or email is None or not location:
        return

    if _run_async(find_user_async(user_id)):
        print("User already exists")
        return

    profile = {
        "user_id": user_id,
        "email": email,
        "location": location,
        "channels": [],
        "interests": [],
        "delivery_frequency": "weekly",
        "email_enabled": True
    }

    _save_user(profile)
    _remember_user(user_id)
    print("User Created")


def choose_interests() -> None:
    """Update the saved interest list for one user."""
    user = _prompt_user("updating interests")
    if not user:
        print("User not found")
        return
    interests = _prompt_text(
        """Enter something you find interesting, \n
        Separated by comma
        
        """
    )
    if interests is None:
        return

    user["interests"] = _parse_interests(interests)
    _save_user(user)

    print("Interests recorded")


def choose_news_channels() -> None:
    """Update the news channels for one user profile."""
    user = _prompt_user("choosing news channels")
    if not user:
        print("User Not Found")
        return
    interests = user.get("interests", [])

    suggested = _normalize_channels(user.get("channels", []))
    if interests:
        suggested_by_interest = _normalize_channels(_run_async(suggests_channels_async(interests)))
        if suggested_by_interest:
            suggested = suggested_by_interest
            print(f"Suggested channels based on interests: {_format_channels(suggested)}")

    channels = _normalize_channels(channel_menu(default=suggested))
    if not channels:
        print("No channels selected")
        return

    user["channels"] = channels
    _save_user(user)
    print("Channel Updated")


def set_frequency() -> None:
    """Change how frequently one user should receive digest emails."""
    user = _prompt_user("setting delivery frequency")
    if not user:
        print("User not found")
        return
    freq = frequency_menu()
    if freq is None:
        print("Prompt cancelled")
        return

    user["delivery_frequency"] = freq
    _save_user(user)

    print("frequency updated")


def stop_email() -> None:
    """Disable email delivery for one user."""
    user = _prompt_user("stopping email delivery")
    if not user:
        print("User not Found")
        return

    user["email_enabled"] = False
    _save_user(user)

    print("email delivery suspended")


def resume_email() -> None:
    """Re-enable email delivery for one user."""
    user = _prompt_user("resuming email delivery")
    if not user:
        print("User Not Found")
        return
    user["email_enabled"] = True
    _save_user(user)

    print("Email Delivery Resumed")


def generate_email_digest() -> None:
    """Kick off one immediate digest run for the selected user."""
    user = _prompt_user("generating an email now")
    if not user:
        print("User Not Found")
        return
    if not user.get("email_enabled", True):
        print("Email Delivery Services Disabled For This User")
        return
    if not _normalize_channels(user.get("channels", [])):
        print("No news channels were configured for this user.")
        print(f"Using default channels for this run: {_format_channels(DEFAULT_CHANNELS)}")

    print(f"Generating digest for {_profile_label(user)}")
    print("This can take a few minutes because it fetches sources and renders each section in sequence.")
    if "set_suppress_console_output" in globals():
        set_suppress_console_output(True)
        try:
            flow_state = run_with_user_request(user)
        finally:
            set_suppress_console_output(False)
    else:
        flow_state = run_with_user_request(user)

    print("Digest generation completed")
    if flow_state.output_path:
        print(f"Saved digest path: {flow_state.output_path}")

    if flow_state.delivery_status == "sent":
        print("Email delivered")
    elif flow_state.delivery_status == "skipped":
        print("Email delivery skipped")
        if flow_state.output_path:
            _print_local_digest_summary(flow_state.output_path)
    elif flow_state.delivery_status == "failed":
        print("Email delivery failed")
        if flow_state.delivery_error:
            print(f"Delivery error: {flow_state.delivery_error}")
        print("The digest was still rendered locally; this usually means SES sandbox or identity verification needs attention.")
        if flow_state.output_path:
            _print_local_digest_summary(flow_state.output_path)


def run_cli() -> None:
    """Run the interactive CLI until the user exits."""
    # The CLI stays synchronous because terminal prompts themselves are sync.
    while True:
        action = main_menu()
        if action is None:
            print("CLI cancelled")
            break
        if action == "Create User":
            create_user()
        elif action == "Choose News Channels":
            choose_news_channels()
        elif action == "Choose Interests":
            choose_interests()
        elif action == "Set Email Delivery Frequency":
            set_frequency()
        elif action == "Stop Email Delivery":
            stop_email()
        elif action == "Resume Email Delivery":
            resume_email()
        elif action == "Generate Email Now":
            generate_email_digest()
            break
        elif action == "Exit":
            break


if __name__ == "__main__":
    run_cli()
