"""Default platform presets for the autonomous search agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class AutonomousPlatformPreset:
    id: str
    display_name: str
    search_url: str
    default_instructions: str


AUTONOMOUS_PLATFORM_LIBRARY: Dict[str, AutonomousPlatformPreset] = {
    "monster": AutonomousPlatformPreset(
        id="monster",
        display_name="Monster",
        search_url="https://www.monster.com/jobs/",
        default_instructions="Use Monster's filters to target US-based software engineering roles with remote or hybrid flexibility.",
    ),
    "wellfound": AutonomousPlatformPreset(
        id="wellfound",
        display_name="Wellfound",
        search_url="https://wellfound.com/jobs",
        default_instructions="Focus on VC-backed startups hiring remotely within the United States.",
    ),
    "builtin": AutonomousPlatformPreset(
        id="builtin",
        display_name="Built In",
        search_url="https://builtin.com/jobs",
        default_instructions="Search for engineering roles in San Francisco, New York, Austin, and remote hubs. Prefer roles mentioning AI, SaaS, or platform teams.",
    ),
    "hired": AutonomousPlatformPreset(
        id="hired",
        display_name="Hired",
        search_url="https://hired.com/job-search",
        default_instructions="Prioritize senior individual contributor roles with compensation above $160k base and remote friendly.",
    ),
    "wellfound-eu": AutonomousPlatformPreset(
        id="wellfound-eu",
        display_name="Wellfound EU",
        search_url="https://wellfound.com/jobs?locations=london",
        default_instructions="Look for EU startups willing to hire remotely; summarize visa/remote restrictions if mentioned.",
    ),
}


def build_default_platform_config() -> List[dict]:
    """Return a serializable list of default platform entries."""

    return [
        {
            "id": preset.id,
            "label": preset.display_name,
            "search_url": preset.search_url,
            "instructions": preset.default_instructions,
            "enabled": True,
        }
        for preset in AUTONOMOUS_PLATFORM_LIBRARY.values()
    ]
