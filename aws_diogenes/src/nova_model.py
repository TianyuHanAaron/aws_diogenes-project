"""Helpers for creating Nova LLM clients."""

from crewai import LLM


def create_nova_lite(*, max_tokens: int = 2600) -> LLM:
    """Create a fresh Nova Lite client for each crew agent."""
    return LLM(
        model="bedrock/amazon.nova-lite-v1:0",
        temperature=0.2,
        max_tokens=max_tokens,
        top_p=0.9,
        top_k=50,
        stop_sequences=["END"],
    )


nova_lite = create_nova_lite()
