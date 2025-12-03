#!/usr/bin/env python3
"""
Activity Manager for handling activity messages with thread support
"""

import logging
from enum import Enum
from typing import Any, Dict, Optional

from activity.base_activity import ActivityType

logger = logging.getLogger(__name__)


class ThreadType(str, Enum):
    """Types of activity threads"""

    APPLICATION = "application"
    GENERAL = "general"


class ActivityManager:
    """
    Manages activity messages with thread support

    Handles thread titles, automatic thread switching, and consistent
    message routing for activity logs.
    """

    def __init__(self, websocket_callback=None, bot_id: str = None):
        """
        Initialize the activity manager

        Args:
            websocket_callback: Callback function to send messages
            bot_id: Bot ID for message identification
        """
        self.websocket_callback = websocket_callback
        self.bot_id = bot_id
        self.current_thread_title = None
        self.current_thread_type = ThreadType.GENERAL
        self.current_thread_status = None

    def set_websocket_callback(self, callback):
        """Set or update the WebSocket callback"""
        self.websocket_callback = callback

    def set_bot_id(self, bot_id: str):
        """Set or update the bot ID"""
        self.bot_id = bot_id

    def start_application_thread(
        self, company_name: str, job_title: str, status: str = "Started"
    ):
        """
        Start a new application thread for job application

        Args:
            company_name: Name of the company
            job_title: Job title being applied to
            status: Application status (Started, Queued, Applied, etc.)
        """
        thread_title = f"{company_name} - {job_title}"
        self.current_thread_title = thread_title
        self.current_thread_type = ThreadType.APPLICATION
        self.current_thread_status = status
        logger.debug(
            f"Started application thread: {self.current_thread_title} "
            f"with status: {status}"
        )

    def update_application_status(self, status: str):
        """
        Update the status of the current application thread

        Args:
            status: New status (Started, Queued, Applied, Failed, etc.)
        """
        is_application = self.current_thread_type == ThreadType.APPLICATION
        if is_application:
            self.current_thread_status = status
            logger.debug(f"Updated application thread status to: {status}")

    def start_general_thread(self, title: str = None):
        """
        Start a general thread (no specific type)

        Args:
            title: Optional thread title, if None will clear current thread
        """
        self.current_thread_title = title
        self.current_thread_type = ThreadType.GENERAL
        logger.debug(f"Started general thread: {self.current_thread_title}")

    def send_activity_message(
        self,
        message: str,
        activity_type: str = ActivityType.ACTION,
        thread_title: Optional[str] = None,
    ):
        """
        Send an activity message with thread support

        Args:
            message: The message to send
            activity_type: Type of activity (action, thinking, result)
            thread_title: Override thread title (if None, uses current)
        """
        if not self.websocket_callback:
            logger.warning("No websocket callback set, cannot send message")
            return

        # Use provided thread_title, or fall back to current_thread_title
        effective_thread_title = thread_title or self.current_thread_title

        message_data = {
            "type": "activity",
            "message": message,
            "activity_type": activity_type,
        }

        # Add bot_id if available
        if self.bot_id:
            message_data["bot_id"] = self.bot_id

        # Add thread_title if available
        if effective_thread_title:
            message_data["thread_title"] = effective_thread_title

        # Add thread_status if available
        if self.current_thread_status:
            message_data["thread_status"] = self.current_thread_status

        try:
            self.websocket_callback(message_data)
            msg_preview = message[:50] + "..." if len(message) > 50 else message
            logger.debug(f"Sent activity message: {msg_preview}")
        except Exception as e:
            logger.error(f"Failed to send activity message: {e}")

    def send_status_update(self, status: str, message: str):
        """
        Send a status update message

        Args:
            status: Status string
            message: Status message
        """
        if not self.websocket_callback:
            logger.warning("No websocket callback set, cannot send update")
            return

        message_data = {
            "type": "status_update",
            "status": status,
            "message": message,
        }

        # Add bot_id if available
        if self.bot_id:
            message_data["bot_id"] = self.bot_id

        try:
            self.websocket_callback(message_data)
            logger.debug(f"Sent status update: {status} - {message}")
        except Exception as e:
            logger.error(f"Failed to send status update: {e}")

    def get_current_thread_info(self) -> Dict[str, Any]:
        """
        Get information about the current thread

        Returns:
            Dict with thread_title and thread_type
        """
        thread_type_value = (
            self.current_thread_type.value if self.current_thread_type else None
        )
        return {
            "thread_title": self.current_thread_title,
            "thread_type": thread_type_value,
        }
