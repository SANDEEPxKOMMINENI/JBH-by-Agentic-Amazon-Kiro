#!/usr/bin/env python3
"""
Resume Searching Action for ZipRecruiter Bot
"""

import logging
from typing import Any, Dict

from ziprecruiter_bot.actions.base_action import BaseAction

logger = logging.getLogger(__name__)


class ResumeSearchingAction(BaseAction):
    """Action to resume the ZipRecruiter searching process"""

    @property
    def action_name(self) -> str:
        return "resume_searching"

    def execute(self) -> Dict[str, Any]:
        """Resume the searching process and browser operations"""
        try:
            if not self.bot.is_running:
                return {
                    "success": False,
                    "message": "Bot is not running",
                    "status": "not_running",
                }

            if self.bot.status != "paused":
                return {
                    "success": False,
                    "message": "Bot is not paused",
                    "status": "not_paused",
                }

            # Resume browser operations if browser operator exists
            if self.bot.browser_operator:
                self.bot.browser_operator.resume_operations()
                self.send_activity_message("Browser operations resumed")

            self.bot.status = "running"

            self.send_status_update("running", "Bot and browser operations resumed")

            self.logger.info(
                f"ZipRecruiter bot {self.bot.bot_id} and browser operations resumed"
            )

            return {
                "success": True,
                "message": "Bot and browser operations resumed",
                "status": "running",
            }

        except Exception as e:
            self.logger.error(f"Failed to resume bot: {e}")
            return {
                "success": False,
                "message": f"Error resuming bot: {str(e)}",
                "status": "error",
            }
