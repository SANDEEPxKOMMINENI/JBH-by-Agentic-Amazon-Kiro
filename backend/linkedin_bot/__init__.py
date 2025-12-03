"""
LinkedIn Bot Package for JobHuntr v2
"""

from linkedin_bot.linkedin_bot import LinkedInBot
from linkedin_bot.linkedin_bot_controller import (
    LinkedInBotController,
    linkedin_bot_controller,
)

__all__ = ["LinkedInBot", "LinkedInBotController", "linkedin_bot_controller"]
