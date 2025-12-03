#!/usr/bin/env python3
"""
Simple Indeed Bot for JobHuntr v2
@file purpose: Simple Indeed automation using BrowserOperator with integrated WebSocket communication
"""

import logging
import os
import sys
from typing import Any, Dict, Optional

from browser.automation import Page

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from browser.browser_operator import BrowserOperator
from indeed_bot.actions import (
    PauseSearchingAction,
    ResumeSearchingAction,
    StartSearchingAction,
    StopSearchingAction,
)

logger = logging.getLogger(__name__)


class IndeedBot:
    """
    Simple Indeed Bot that automates Indeed job search and queue

    Features:
    - Uses BrowserOperator for modern async browser automation
    - Integrated WebSocket communication for real-time updates
    - Search and queue jobs (no auto-apply)
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

        # Bot thread reference (for cleanup)
        self.bot_thread = None

        # Bot state
        self.current_url = ""
        self.status = "idle"  # idle, running, paused, stopped, error

    def start_searching(self) -> Dict[str, Any]:
        """Start the Indeed searching process using StartSearchingAction"""
        action = StartSearchingAction(self)
        return action.execute()

    def stop_searching(self) -> Dict[str, Any]:
        """Stop the Indeed searching process using StopSearchingAction"""
        action = StopSearchingAction(self)
        return action.execute()

    def pause_searching(self) -> Dict[str, Any]:
        """Pause the searching process using PauseSearchingAction"""
        action = PauseSearchingAction(self)
        return action.execute()

    def resume_searching(self) -> Dict[str, Any]:
        """Resume the searching process using ResumeSearchingAction"""
        action = ResumeSearchingAction(self)
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

        bot = IndeedBot("test_bot", "test_user", websocket_callback=test_callback)

        # Start searching
        result = bot.start_searching()
        logger.info(f"Start result: {result}")

        if result["success"]:
            # Wait a few seconds
            import time

            time.sleep(5)

            # Stop searching
            stop_result = bot.stop_searching()
            logger.info(f"Stop result: {stop_result}")

    test_bot()
