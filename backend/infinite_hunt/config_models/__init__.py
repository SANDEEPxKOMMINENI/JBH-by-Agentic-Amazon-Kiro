"""Typed bot config models used by infinite hunt automation."""

from .autonomous import AutonomousBotConfig, AutonomousPlatformSettings
from .dice import DiceBotConfig
from .glassdoor import GlassdoorBotConfig
from .indeed import IndeedBotConfig, IndeedFilters
from .linkedin import LinkedInBotConfig, LinkedInFilters
from .ziprecruiter import ZipRecruiterBotConfig

__all__ = [
    "AutonomousBotConfig",
    "AutonomousPlatformSettings",
    "DiceBotConfig",
    "GlassdoorBotConfig",
    "IndeedBotConfig",
    "IndeedFilters",
    "LinkedInBotConfig",
    "LinkedInFilters",
    "ZipRecruiterBotConfig",
]
