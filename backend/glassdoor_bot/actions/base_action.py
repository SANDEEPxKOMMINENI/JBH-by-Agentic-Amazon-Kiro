#!/usr/bin/env python3
"""
Base Action class for Glassdoor Bot actions
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from activity.base_activity import ActivityType
from shared.activity_manager import ActivityManager

logger = logging.getLogger(__name__)


class BaseAction(ABC):
    """
    Base class for all Glassdoor Bot actions

    Provides common functionality and interface for all actions
    """

    def __init__(self, bot_instance):
        """
        Initialize action with bot instance

        Args:
            bot_instance: The GlassdoorBot instance this action operates on
        """
        self.bot = bot_instance
        self.logger = logger

        # Initialize activity manager
        websocket_callback = (
            self.bot.websocket_callback
            if hasattr(self.bot, "websocket_callback")
            else None
        )
        bot_id = self.bot.bot_id if hasattr(self.bot, "bot_id") else None
        self.activity_manager = ActivityManager(
            websocket_callback=websocket_callback, bot_id=bot_id
        )

    def send_websocket_message(self, message: Dict[str, Any]):
        """Send message via WebSocket if callback exists"""
        if self.bot.websocket_callback:
            try:
                self.bot.websocket_callback(message)
            except Exception as e:
                self.logger.error(f"Failed to send WebSocket message: {e}")

    def send_status_update(self, status: str, message: str):
        """Send status update via activity manager"""
        self.activity_manager.send_status_update(status, message)

    def send_activity_message(
        self,
        message: str,
        activity_type: str = ActivityType.ACTION,
        thread_title: Optional[str] = None,
    ):
        """Send activity message via activity manager"""
        self.activity_manager.send_activity_message(
            message, activity_type, thread_title
        )

    @abstractmethod
    def execute(self, *args, **kwargs) -> Dict[str, Any]:
        """
        Execute the action

        Returns:
            Dict containing success status and relevant information
        """
        pass

    @property
    @abstractmethod
    def action_name(self) -> str:
        """Return the name of this action"""
        pass
