"""
Infinite hunt configuration helpers.

This module exports strongly typed Pydantic models that describe the config payloads
shared across bot controllers.  They are useful when orchestrating runs from scripts
or AI agents because they guarantee field names and defaults match the backend.
"""

from .config_models import (
    AutonomousBotConfig,
    DiceBotConfig,
    GlassdoorBotConfig,
    IndeedBotConfig,
    LinkedInBotConfig,
    ZipRecruiterBotConfig,
)
from .manager import InfiniteHuntManager, initialize_infinite_hunt_manager

__all__ = [
    "AutonomousBotConfig",
    "DiceBotConfig",
    "GlassdoorBotConfig",
    "IndeedBotConfig",
    "LinkedInBotConfig",
    "ZipRecruiterBotConfig",
    "InfiniteHuntManager",
    "initialize_infinite_hunt_manager",
]
