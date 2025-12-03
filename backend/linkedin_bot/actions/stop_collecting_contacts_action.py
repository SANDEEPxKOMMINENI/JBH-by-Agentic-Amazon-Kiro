#!/usr/bin/env python3
"""
Stop Collecting Contacts Action for LinkedIn Bot
"""

import logging
from typing import Any

from linkedin_bot.actions.base_action import BaseAction

logger = logging.getLogger(__name__)


class StopCollectingContactsAction(BaseAction):
    """Action to stop the contact collection process"""

    @property
    def action_name(self) -> str:
        return "stop_collecting_contacts"

    def execute(self) -> dict[str, Any]:
        """
        Stop the contact collection process gracefully
        """
        try:
            self.logger.info("Stopping contact collection")

            self.send_status_update("stopping", "Stopping contact collection...")

            # Set flag to stop collection
            self.bot.stop_collection_requested = True

            # Send activity message
            self.send_activity_message("**Contact collection stop requested**")

            self.logger.info("Contact collection stop signal sent")

            return {
                "success": True,
                "message": "Contact collection stop requested",
                "status": "stopping",
            }

        except Exception as e:
            self.logger.error(f"Failed to stop contact collection: {e}")

            return {
                "success": False,
                "message": f"Error stopping collection: {str(e)}",
                "status": "error",
            }
