#!/usr/bin/env python3
"""
Simple LinkedIn Bot for JobHuntr v2
@file purpose: Simple LinkedIn automation using BrowserOperator with integrated WebSocket communication  # noqa: E501
"""

# import asyncio - removed for sync conversion
import logging
import os
import sys
from typing import Any, Dict, Optional

from browser.automation import Page  # noqa: E402

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from browser.browser_operator import BrowserOperator  # noqa: E402
from linkedin_bot.actions import (  # noqa: E402
    PauseHuntingAction,
    ResumeHuntingAction,
    StartHuntingAction,
    StopHuntingAction,
)

logger = logging.getLogger(__name__)


class LinkedInBot:
    """
    Simple LinkedIn Bot that automates basic LinkedIn interactions

    Features:
    - Uses BrowserOperator for modern async browser automation
    - Integrated WebSocket communication for real-time updates
    - Clean API without parameter passing overhead
    """

    def __init__(
        self,
        bot_id: str,
        user_id: str,
        websocket_callback=None,
        workflow_run_id: Optional[str] = None,
    ):
        self.bot_id = bot_id
        self.user_id = user_id
        self.is_running = False
        self.browser_operator: Optional[BrowserOperator] = None
        self.page: Optional[Page] = None
        self.websocket_callback = websocket_callback
        self.workflow_run_id = workflow_run_id  # Store for passing to actions

        # Bot state
        self.current_url = ""
        self.status = "idle"  # idle, running, paused, stopped, error

    def start_hunting(
        self, linkedin_starter_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """Start the LinkedIn hunting process using StartHuntingAction"""
        action = StartHuntingAction(self)
        return action.execute(linkedin_starter_url)

    def stop_hunting(self) -> Dict[str, Any]:
        """Stop the LinkedIn hunting process using StopHuntingAction"""
        action = StopHuntingAction(self)
        return action.execute()

    def pause_hunting(self) -> Dict[str, Any]:
        """Pause the hunting process using PauseHuntingAction"""
        action = PauseHuntingAction(self)
        return action.execute()

    def resume_hunting(self) -> Dict[str, Any]:
        """Resume the hunting process using ResumeHuntingAction"""
        action = ResumeHuntingAction(self)
        return action.execute()

    def get_status(self) -> Dict[str, Any]:
        """Get current bot status"""
        return {
            "bot_id": self.bot_id,
            "is_running": self.is_running,
            "status": self.status,
            "current_url": self.current_url,
            "has_browser": self.browser_operator is not None
            and self.browser_operator.is_ready(),
            "has_page": self.page is not None,
        }


if __name__ == "__main__":
    # Test the bot
    def test_bot():
        # Test callback function
        def test_callback(message):
            logger.info(f"Callback: {message}")

        bot = LinkedInBot("test_bot", "test_user", websocket_callback=test_callback)

        # Start hunting
        result = bot.start_hunting()
        logger.info(f"Start result: {result}")

        if result["success"]:
            # Wait a few seconds
            import time  # noqa: E402

            time.sleep(5)

            # Stop hunting
            stop_result = bot.stop_hunting()
            logger.info(f"Stop result: {stop_result}")

    test_bot()
