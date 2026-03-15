import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def test_cli_app_imports_with_src_layout():
    import cli.app  # noqa: F401


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


def test_delete_saved_user_removes_profile_and_forgets_last_user():
    import cli.app as app

    app._LAST_USER_ID = "demo"
    user = {"user_id": "demo", "location": "Sydney", "email": "demo@example.com"}

    with patch("cli.app._prompt_user", return_value=user), patch(
        "cli.app.questionary.confirm"
    ) as confirm_mock, patch("cli.app.load_profiles_async", new=AsyncMock(return_value=[user])), patch(
        "cli.app.save_profiles_async", new=AsyncMock()
    ) as save_profiles_async:
        confirm_mock.return_value.ask.return_value = True
        app.delete_saved_user()

    save_profiles_async.assert_awaited_once_with([])
    assert app._LAST_USER_ID is None


def test_generate_email_digest_formats_delivery_error_without_preview():
    import cli.app as app

    flow_state = SimpleNamespace(
        output_path="/tmp/email_digest.html",
        delivery_status="failed",
        delivery_error=(
            "An error occurred (MessageRejected) when calling the SendEmail operation: "
            "Email address is not verified."
        ),
    )
    user = {
        "user_id": "demo",
        "location": "Sydney",
        "email": "demo@example.com",
        "email_enabled": True,
        "channels": ["global"],
    }

    with patch("cli.app._prompt_user", return_value=user), patch(
        "cli.app.run_with_user_request", return_value=flow_state
    ), patch("builtins.print") as print_mock:
        app.generate_email_digest()

    printed_lines = [" ".join(str(part) for part in call.args) for call in print_mock.call_args_list]
    assert any("Email delivery failed" in line for line in printed_lines)
    assert any("Amazon SES blocked delivery" in line for line in printed_lines)
    assert not any("Local digest preview" in line for line in printed_lines)
