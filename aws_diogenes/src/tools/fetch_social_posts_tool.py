from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Dict, List, Type

from tools._data import load_mock_data


class FetchSocialPostsInput(BaseModel):
    user_id: str = Field(..., description="User ID requesting posts")


class FetchSocialPostsTool(BaseTool):
    name: str = "fetch_social_posts"
    description: str = "Retrieve recent posts from acquaintances"
    args_schema: Type[BaseModel] = FetchSocialPostsInput

    def _run(self, user_id: str) -> List[Dict]:
        posts = load_mock_data("mock_posts.json")

        return [post for post in posts if post.get("user_id") == user_id]
