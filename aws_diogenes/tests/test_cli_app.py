import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def test_cli_app_imports_with_src_layout():
    import cli.app  # noqa: F401


def test_choose_interests_persists_updated_user():
    import cli.app as app

    updated_profiles = [{"user_id": "demo", "interests": ["space"]}]

    with patch("cli.app.questionary.text") as text_mock, patch(
        "cli.app.find_user", return_value={"user_id": "demo", "interests": []}
    ), patch("cli.app.load_profiles", return_value=[{"user_id": "demo", "interests": []}]), patch(
        "cli.app.save_profiles"
    ) as save_profiles:
        text_mock.return_value.ask.side_effect = ["demo", "space"]
        app.choose_interests()

    save_profiles.assert_called_once_with(updated_profiles)


def test_choose_news_channels_persists_backend_channel_ids():
    import cli.app as app

    updated_profiles = [{"user_id": "demo", "channels": ["global", "interest"]}]

    with patch("cli.app.questionary.text") as text_mock, patch(
        "cli.app.find_user", return_value={"user_id": "demo", "interests": ["space"], "channels": []}
    ), patch("cli.app.suggests_channels", return_value=["Global", "Interested Topics"]), patch(
        "cli.app.channel_menu", return_value=["global", "interest"]
    ), patch("cli.app.load_profiles", return_value=[{"user_id": "demo", "channels": []}]), patch(
        "cli.app.save_profiles"
    ) as save_profiles:
        text_mock.return_value.ask.return_value = "demo"
        app.choose_news_channels()

    save_profiles.assert_called_once_with(updated_profiles)


def test_channel_menu_supports_empty_defaults():
    import cli.menus as menus

    with patch("cli.menus.questionary.checkbox") as checkbox:
        checkbox.return_value.ask.return_value = ["global"]
        result = menus.channel_menu(default=[])

    assert result == ["global"]
    choices = checkbox.call_args.kwargs["choices"]
    assert all(not choice.checked for choice in choices)


def test_run_cli_exits_after_generate_email_action():
    import cli.app as app

    with patch("cli.app.main_menu", side_effect=["Generate Email Now", "Create User"]), patch(
        "cli.app.generate_email_digest"
    ) as generate_email_digest, patch("cli.app.create_user") as create_user:
        app.run_cli()

    generate_email_digest.assert_called_once()
    create_user.assert_not_called()
