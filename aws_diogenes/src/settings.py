"""Environment-backed configuration values for runtime tools."""

from __future__ import annotations

import os

from dotenv import load_dotenv


load_dotenv()

NEWSAPI_API_KEY = os.getenv("NEWSAPI_API_KEY")
GUARDIAN_KEY = os.getenv("GUARDIAN_KEY")

PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY")
PIXABAY_KEY = os.getenv("PIXABAY_KEY")
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY")
WEBCAMS_KEY = os.getenv("WEBCAMS_KEY")
