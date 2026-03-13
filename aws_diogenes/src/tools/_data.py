import json
from pathlib import Path
from typing import Any


def load_mock_data(filename: str) -> Any:
    data_path = Path(__file__).resolve().parent.parent / "data" / filename
    with data_path.open("r", encoding="utf-8") as f:
        return json.load(f)
