import sys
from pathlib import Path
from unittest.mock import Mock, patch

import requests


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from tools.fetch_news_tool import FetchNewsTool


def _rate_limit_error() -> requests.HTTPError:
    """Build a representative NewsAPI 429 error with a response attached."""
    response = Mock(status_code=429)
    error = requests.HTTPError("429 Client Error: Too Many Requests")
    error.response = response
    return error


def test_fetch_queries_stops_calling_newsapi_after_rate_limit():
    tool = FetchNewsTool()
    with patch.object(FetchNewsTool, "fetch_newsapi", side_effect=_rate_limit_error()) as fetch_newsapi:
        with patch.object(FetchNewsTool, "fetch_guardian", return_value=[]) as fetch_guardian:
            with patch.object(FetchNewsTool, "fetch_rss", return_value=[]) as fetch_rss:
                tool.fetch_queries(["first query", "second query", "third query"])

    assert fetch_newsapi.call_count == 1
    assert fetch_guardian.call_count == 3
    assert fetch_rss.call_count == 1


def test_fetch_queries_keeps_retrying_non_rate_limited_provider_errors():
    tool = FetchNewsTool()
    with patch.object(FetchNewsTool, "fetch_newsapi", side_effect=RuntimeError("temporary upstream error")) as fetch_newsapi:
        with patch.object(FetchNewsTool, "fetch_guardian", return_value=[]) as fetch_guardian:
            with patch.object(FetchNewsTool, "fetch_rss", return_value=[]) as fetch_rss:
                tool.fetch_queries(["first query", "second query"])

    assert fetch_newsapi.call_count == 2
    assert fetch_guardian.call_count == 2
    assert fetch_rss.call_count == 1
