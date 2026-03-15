"""Helpers for YAML-configured agent/task execution without nested CrewAI crews."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import yaml

from nova_model import create_nova_lite


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file into a dictionary."""
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Expected mapping in {path}")
    return payload


async def load_yaml_async(path: Path) -> dict[str, Any]:
    """Load a YAML file without blocking the event loop."""
    return await asyncio.to_thread(load_yaml, path)


def fill_placeholders(text: str, values: dict[str, Any]) -> str:
    """Fill `{name}` placeholders while leaving unrelated braces untouched."""
    return re.sub(
        r"\{([a-zA-Z0-9_]+)\}",
        lambda match: str(values.get(match.group(1), match.group(0))),
        text or "",
    )


def build_task_prompt(
    agent_config: dict[str, Any],
    task_config: dict[str, Any],
    values: dict[str, Any],
    payloads: dict[str, Any],
) -> str:
    """Build a direct LLM prompt from YAML-defined agent and task config."""
    parts = [
        f"Role: {fill_placeholders(str(agent_config.get('role', '')), values)}",
        f"Goal: {fill_placeholders(str(agent_config.get('goal', '')), values)}",
        f"Backstory: {fill_placeholders(str(agent_config.get('backstory', '')), values)}",
        "",
        "Task:",
        fill_placeholders(str(task_config.get("description", "")), values),
    ]
    expected_output = str(task_config.get("expected_output", "") or "").strip()
    if expected_output:
        parts.extend(["", "Expected Output:", fill_placeholders(expected_output, values)])
    guardrail = str(task_config.get("guardrail", "") or "").strip()
    if guardrail:
        parts.extend(["", "Guardrail:", fill_placeholders(guardrail, values)])
    for name, payload in payloads.items():
        parts.extend(["", f"{name}:", json.dumps(payload, ensure_ascii=True)])
    return "\n".join(parts).strip()


def call_nova_text(prompt: str, *, max_tokens: int = 2600) -> str:
    """Run a direct Nova text call."""
    return str(create_nova_lite(max_tokens=max_tokens).call(prompt)).strip()


async def call_nova_text_async(prompt: str, *, max_tokens: int = 2600) -> str:
    """Run a direct Nova text call without blocking the event loop."""
    return await asyncio.to_thread(call_nova_text, prompt, max_tokens=max_tokens)


def extract_json(raw: str) -> dict | list | None:
    """Extract a JSON object or list from model output."""
    text = str(raw or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    candidates = [text]
    first_object = text.find("{")
    last_object = text.rfind("}")
    if first_object != -1 and last_object != -1 and last_object > first_object:
        candidates.append(text[first_object:last_object + 1])
    first_list = text.find("[")
    last_list = text.rfind("]")
    if first_list != -1 and last_list != -1 and last_list > first_list:
        candidates.append(text[first_list:last_list + 1])
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except Exception:
            continue
        if isinstance(payload, (dict, list)):
            return payload
    return None


def strip_code_fences(text: str) -> str:
    """Strip fenced code wrappers from model output."""
    fenced = re.search(r"```(?:html|json)?\s*(.*?)```", text or "", flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    return str(text or "").strip()
