#!/usr/bin/env python3
"""
Pause Hunting Action for LinkedIn Bot
"""

import logging
from typing import Any, Dict

from linkedin_bot.actions.base_action import BaseAction

logger = logging.getLogger(__name__)


class PauseHuntingAction(BaseAction):
    """Action to pause the LinkedIn hunting process"""

    @property
    def action_name(self) -> str:
        return "pause_hunting"

    def execute(self) -> Dict[str, Any]:
        """Pause the hunting process and browser operations"""
        try:
            if not self.bot.is_running:
                return {
                    "success": False,
                    "message": "Bot is not running",
                    "status": "not_running",
                }

            # Pause browser operations if browser operator exists
            if self.bot.browser_operator:
                self.bot.browser_operator.pause_operations()
                self.send_activity_message("Browser operations paused")

            self.bot.status = "paused"

            self.send_status_update("paused", "Bot and browser operations paused")

            self.logger.info(
                f"LinkedIn bot {self.bot.bot_id} and browser operations paused"
            )

            return {
                "success": True,
                "message": "Bot and browser operations paused",
                "status": "paused",
            }

        except Exception as e:
            self.logger.error(f"Failed to pause bot: {e}")
            return {
                "success": False,
                "message": f"Error pausing bot: {str(e)}",
                "status": "error",
            }
