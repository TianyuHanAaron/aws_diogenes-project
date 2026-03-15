"""YAML-driven helpers for the seasonal events section."""

from __future__ import annotations

from pathlib import Path
import random

from crews.runtime_utils import (
    build_task_prompt,
    call_nova_text_async,
    extract_json,
    load_yaml_async,
    strip_code_fences,
)


CONFIG_DIR = Path(__file__).resolve().parent / "config"
VARIATION_ANGLES = [
    "focus on the social customs first, then explain the history",
    "lead with timing and public atmosphere before the cultural significance",
    "emphasize the origin story first, then describe how people observe it today",
    "focus on where it is celebrated first, then explain the customs and meaning",
]


async def generate_seasonal_section(events, request, current_dt, window_end) -> str:
    """Run the staged seasonal prompts and return the final HTML fragment."""
    print("Seasonal events: identifying upcoming festivals...")
    agents, tasks = await load_yaml_async(CONFIG_DIR / "agents.yaml"), await load_yaml_async(CONFIG_DIR / "tasks.yaml")
    variation_angle = random.choice(VARIATION_ANGLES)
    values = {
        "current_date": current_dt.strftime("%Y-%m-%d"),
        "window_end_date": window_end.strftime("%Y-%m-%d"),
        "location": request.location,
        "hemisphere": request.hemisphere,
        "variation_angle": variation_angle,
        "variation_seed": str(random.randint(1000, 9999)),
    }
    serialized_events = [item.model_dump() for item in events]

    festivals = await _run_json_stage(
        agents["seasonal_calendar_agent"],
        tasks["seasonal_calendar_identification_task"],
        values,
        {"seasonal_events": serialized_events},
    )
    print("Seasonal events: researching festival context...")
    researched_festivals = await _run_json_stage(
        agents["seasonal_customs_agent"],
        tasks["seasonal_customs_research_task"],
        values,
        {"festivals": festivals, "seasonal_events": serialized_events},
    )
    print("Seasonal events: identifying seasonal flora...")
    flora = await _run_json_stage(
        agents["seasonal_flora_agent"],
        tasks["seasonal_flora_research_task"],
        values,
        {"seasonal_events": serialized_events},
    )
    print("Seasonal events: summarizing entries...")
    summary = await _run_json_stage(
        agents["seasonal_summary_agent"],
        tasks["seasonal_summary_task"],
        values,
        {"festivals": researched_festivals, "flora": flora},
    )
    print("Seasonal events: reviewing final entries...")
    reviewed_summary = await _run_json_stage(
        agents["seasonal_final_review_agent"],
        tasks["seasonal_final_review_task"],
        values,
        {"seasonal_entries": summary},
    )
    prompt = build_task_prompt(
        agents["seasonal_layout_agent"],
        tasks["seasonal_layout_task"],
        values,
        {"seasonal_entries": reviewed_summary},
    )
    print("Seasonal events: formatting section...")
    return strip_code_fences(await call_nova_text_async(prompt))


async def _run_json_stage(agent_config: dict, task_config: dict, values: dict, payloads: dict) -> dict | list:
    """Render one YAML-defined seasonal stage and decode its JSON response."""
    prompt = build_task_prompt(agent_config, task_config, values, payloads)
    payload = extract_json(await call_nova_text_async(prompt))
    if isinstance(payload, (dict, list)):
        return payload
    return {} if "JSON object" in str(task_config.get("expected_output", "")) else []
