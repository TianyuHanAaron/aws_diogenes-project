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
