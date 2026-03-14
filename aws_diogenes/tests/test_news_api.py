import os
import sys
from pathlib import Path
from unittest.mock import patch


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from tools.fetch_news_tool import FetchNewsTool


tool = FetchNewsTool()

with patch.dict(os.environ, {"NEWSAPI_API_KEY": "", "NEWS_API_KEY": ""}, clear=False):
    result = tool.run(query="technology")


if __name__ == "__main__":
    print(len(result))
    print(result[0])
