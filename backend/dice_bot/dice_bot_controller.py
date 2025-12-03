#!/usr/bin/env python3
"""
Dice Bot Controller for JobHuntr v2
@file purpose: Manage Dice bot instances and WebSocket communication
"""

import logging
import os
import queue
import sys
import threading
import uuid
from threading import Lock
from typing import Any, Dict, List, Optional

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from dice_bot.dice_bot import DiceBot

logger = logging.getLogger(__name__)


class DiceBotController:
    """Controller to manage Dice bot instances and activity polling"""

    def __init__(self):
        self.bots: Dict[str, DiceBot] = {}
        # Store session IDs for polling
        self.polling_sessions: Dict[str, str] = {}
        # Store activity messages for polling
        self.activity_messages: Dict[str, List[Dict]] = {}
        # Track sessions that are being stopped
        self.stopping_sessions: set = set()
        self._message_lock = Lock()  # Thread safety for activity_messages

    def register_polling_session(self, workflow_run_id: str):
        """Register a workflow run for activity polling"""
        self.polling_sessions[workflow_run_id] = workflow_run_id
        logger.info(f"Registered polling for workflow run: {workflow_run_id}")

    def unregister_polling_session(self, workflow_run_id: str):
        """Unregister a polling session"""
        if workflow_run_id in self.polling_sessions:
            del self.polling_sessions[workflow_run_id]
            logger.info(f"Unregistered polling for workflow run: {workflow_run_id}")

    def has_polling_session(self, workflow_run_id: str) -> bool:
        """Check if a workflow run is registered for polling"""
        return workflow_run_id in self.polling_sessions

    def cleanup_session_data(self, workflow_run_id: str):
        """Clean up workflow run data to prevent memory leaks"""
        if workflow_run_id in self.activity_messages:
            del self.activity_messages[workflow_run_id]
            logger.debug(
                f"Cleaned up activity messages for workflow run {workflow_run_id}"
            )

        if workflow_run_id in self.polling_sessions:
            del self.polling_sessions[workflow_run_id]
            logger.debug(f"Cleaned up polling for workflow run {workflow_run_id}")

    def get_active_bot(self, workflow_run_id: str):
        """Get the active bot for a workflow run"""
        return self.bots.get(workflow_run_id)

    def is_bot_running(self, workflow_run_id: str) -> bool:
        """Check if a bot is currently running for a workflow run"""
        bot = self.bots.get(workflow_run_id)
        return bot is not None and getattr(bot, "is_running", False)

    def _send_activity_message(self, workflow_run_id: str, message: Dict[str, Any]):
        """Store activity message for frontend polling"""
        if not self.has_polling_session(workflow_run_id):
            logger.debug(
                f"No polling session for workflow run {workflow_run_id}, skipping message"
            )
            return

        # Store message for frontend polling (thread-safe)
        with self._message_lock:
            if workflow_run_id not in self.activity_messages:
                self.activity_messages[workflow_run_id] = []

            # Add message and limit queue size to prevent memory issues
            self.activity_messages[workflow_run_id].append(message)

            # Keep only the last 10000 messages per workflow run
            MAX_MESSAGES_PER_WORKFLOW_RUN = 10000
            if (
                len(self.activity_messages[workflow_run_id])
                > MAX_MESSAGES_PER_WORKFLOW_RUN
            ):
                self.activity_messages[workflow_run_id] = self.activity_messages[
                    workflow_run_id
                ][-MAX_MESSAGES_PER_WORKFLOW_RUN:]
                logger.debug(
                    f"Trimmed activity queue for workflow run {workflow_run_id} to {MAX_MESSAGES_PER_WORKFLOW_RUN} messages"
                )

            logger.debug(
                f"Stored activity message for workflow run {workflow_run_id}: {message.get('message', 'No message')}"
            )

    def start_searching_controller(
        self,
        user_id: str,
        workflow_run_id: str,
        _bot_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Start searching for a workflow run

        Args:
            user_id: User ID
            workflow_run_id: Workflow run ID (may include user_session_ prefix, will be normalized)
            _bot_config: Optional bot configuration (unused, kept for API compatibility)
        """
        try:
            # Normalize workflow_run_id by removing user_session_ prefix if present
            # This handles both Infinite Hunt (with prefix) and regular runs (without prefix)
            if workflow_run_id.startswith("user_session_"):
                # Extract just the UUID portion after user_session_
                parts = workflow_run_id.split(
                    "_", 2
                )  # Split into ['user', 'session', 'uuid...']
                if len(parts) >= 3:
                    workflow_run_id = (
                        parts[2].split("_", 1)[0] if "_" in parts[2] else parts[2]
                    )
                    logger.info(
                        f"Normalized workflow_run_id from user_session_ prefix to: {workflow_run_id}"
                    )

            # Check if bot already exists for this workflow run
            if workflow_run_id in self.bots:
                bot = self.bots[workflow_run_id]
                if bot.is_running:
                    return {
                        "success": False,
                        "message": "Bot is already running for this session",
                        "bot_id": bot.bot_id,
                    }
                else:
                    # Remove stopped bot and create new one
                    del self.bots[workflow_run_id]

            # Create callback function for this workflow run
            def activity_callback(message):
                self._send_activity_message(workflow_run_id, message)

            # Create new bot with callback and workflow run ID
            bot_id = f"dice_bot_{workflow_run_id}_{uuid.uuid4().hex[:8]}"
            bot = DiceBot(
                bot_id,
                user_id,
                websocket_callback=activity_callback,
                workflow_run_id=workflow_run_id,
            )
            self.bots[workflow_run_id] = bot

            logger.info(
                f"Created new Dice bot for workflow run {workflow_run_id}: {bot_id}"
            )

            # Run bot operations in a separate thread to avoid async/sync conflicts
            def run_bot_in_thread():
                try:
                    logger.info(
                        f"Starting bot thread for workflow run {workflow_run_id}"
                    )
                    result = bot.start_searching()
                    logger.info(
                        f"Bot thread completed for workflow run {workflow_run_id}: {result}"
                    )

                    # If bot failed, clean it up
                    if not result.get("success", False):
                        logger.error(
                            f"Bot failed for workflow run {workflow_run_id}, cleaning up"
                        )
                        if workflow_run_id in self.bots:
                            del self.bots[workflow_run_id]
                        self._send_activity_message(
                            workflow_run_id,
                            {
                                "type": "error",
                                "message": f"Bot failed: {result.get('message', 'Unknown error')}",
                            },
                        )
                except Exception as e:
                    logger.error(
                        f"Bot thread error for workflow run {workflow_run_id}: {e}"
                    )
                    # Clean up failed bot
                    if workflow_run_id in self.bots:
                        del self.bots[workflow_run_id]
                    self._send_activity_message(
                        workflow_run_id,
                        {"type": "error", "message": f"Bot thread error: {str(e)}"},
                    )

            # Start the bot in a separate thread (non-blocking)
            bot_thread = threading.Thread(target=run_bot_in_thread, daemon=True)
            bot_thread.start()

            # Return immediately with success status
            return {
                "success": True,
                "message": "Bot started successfully in background",
                "status": "started",
                "bot_id": bot_id,
                "workflow_run_id": workflow_run_id,
            }

        except Exception as e:
            logger.error(
                f"Failed to start searching for workflow run {workflow_run_id}: {e}"
            )

            # Cleanup on error
            if workflow_run_id in self.bots:
                del self.bots[workflow_run_id]

            self._send_activity_message(
                workflow_run_id,
                {"type": "error", "message": f"Failed to start searching: {str(e)}"},
            )

            return {
                "success": False,
                "message": f"Failed to start searching: {str(e)}",
                "workflow_run_id": workflow_run_id,
            }

    def stop_searching_controller(self, workflow_run_id: str) -> Dict[str, Any]:
        """Stop searching for a workflow run"""
        try:
            # Normalize workflow_run_id by removing user_session_ prefix if present
            if workflow_run_id.startswith("user_session_"):
                parts = workflow_run_id.split("_", 2)
                if len(parts) >= 3:
                    workflow_run_id = (
                        parts[2].split("_", 1)[0] if "_" in parts[2] else parts[2]
                    )
                    logger.info(
                        f"Normalized workflow_run_id for stop: {workflow_run_id}"
                    )

            # Check if already stopping this workflow run
            if workflow_run_id in self.stopping_sessions:
                logger.info(
                    f"Workflow run {workflow_run_id} is already being stopped, skipping"
                )
                return {
                    "success": True,
                    "message": "Workflow run is already being stopped",
                    "workflow_run_id": workflow_run_id,
                }

            if workflow_run_id not in self.bots:
                return {
                    "success": False,
                    "message": "No active bot found for this session",
                    "workflow_run_id": workflow_run_id,
                }

            # Mark session as being stopped
            self.stopping_sessions.add(workflow_run_id)

            bot = self.bots[workflow_run_id]
            bot_id = bot.bot_id

            logger.info(f"Stopping bot {bot_id} for workflow run {workflow_run_id}")

            # CRITICAL: Set is_running to False IMMEDIATELY before spawning stop thread
            # This ensures the main bot thread sees the stop signal right away
            bot.is_running = False
            bot.status = "stopping"
            logger.info(f"Set is_running=False for bot {bot_id}")

            # Run bot stop operation in a separate thread to avoid async/sync conflicts
            result_queue = queue.Queue()

            def run_stop_in_thread():
                try:
                    result = bot.stop_searching()
                    result_queue.put(result)
                except Exception as e:
                    logger.error(
                        f"Bot stop thread error for workflow run {workflow_run_id}: {e}"
                    )
                    result_queue.put(
                        {
                            "success": False,
                            "message": f"Bot stop thread error: {str(e)}",
                        }
                    )

            # Start the stop operation in a separate thread
            stop_thread = threading.Thread(target=run_stop_in_thread, daemon=True)
            stop_thread.start()

            # Wait for result (with timeout)
            try:
                result = result_queue.get(timeout=10)  # 10 second timeout
            except queue.Empty:
                result = {"success": False, "message": "Bot stop operation timed out"}

            # Remove bot from tracking and ensure complete cleanup
            if workflow_run_id in self.bots:
                del self.bots[workflow_run_id]

            # Clean up session data to prevent memory leaks
            self.cleanup_session_data(workflow_run_id)

            # Remove from stopping sessions
            self.stopping_sessions.discard(workflow_run_id)

            logger.info(
                f"Bot {bot_id} completely removed from workflow run {workflow_run_id}"
            )

            return {**result, "bot_id": bot_id, "workflow_run_id": workflow_run_id}

        except Exception as e:
            logger.error(
                f"Failed to stop searching for workflow run {workflow_run_id}: {e}"
            )

            # Force cleanup
            if workflow_run_id in self.bots:
                del self.bots[workflow_run_id]

            # Clean up session data even on error
            self.cleanup_session_data(workflow_run_id)
            self.stopping_sessions.discard(workflow_run_id)

            self._send_activity_message(
                workflow_run_id,
                {"type": "error", "message": f"Failed to stop searching: {str(e)}"},
            )

            logger.info(f"Force cleanup completed for workflow run {workflow_run_id}")

            return {
                "success": False,
                "message": f"Failed to stop searching: {str(e)}",
                "workflow_run_id": workflow_run_id,
            }

    def pause_searching_controller(self, workflow_run_id: str) -> Dict[str, Any]:
        """Pause searching for a workflow run"""
        try:
            # Normalize workflow_run_id
            if workflow_run_id.startswith("user_session_"):
                parts = workflow_run_id.split("_", 2)
                if len(parts) >= 3:
                    workflow_run_id = (
                        parts[2].split("_", 1)[0] if "_" in parts[2] else parts[2]
                    )

            if workflow_run_id not in self.bots:
                return {
                    "success": False,
                    "message": "No active bot found for this workflow run",
                    "workflow_run_id": workflow_run_id,
                }

            bot = self.bots[workflow_run_id]

            result = bot.pause_searching()

            return {**result, "bot_id": bot.bot_id, "workflow_run_id": workflow_run_id}

        except Exception as e:
            logger.error(
                f"Failed to pause searching for workflow run {workflow_run_id}: {e}"
            )
            return {
                "success": False,
                "message": f"Failed to pause searching: {str(e)}",
                "workflow_run_id": workflow_run_id,
            }

    def resume_searching_controller(self, workflow_run_id: str) -> Dict[str, Any]:
        """Resume searching for a workflow run"""
        try:
            # Normalize workflow_run_id
            if workflow_run_id.startswith("user_session_"):
                parts = workflow_run_id.split("_", 2)
                if len(parts) >= 3:
                    workflow_run_id = (
                        parts[2].split("_", 1)[0] if "_" in parts[2] else parts[2]
                    )

            if workflow_run_id not in self.bots:
                return {
                    "success": False,
                    "message": "No active bot found for this workflow run",
                    "workflow_run_id": workflow_run_id,
                }

            bot = self.bots[workflow_run_id]

            result = bot.resume_searching()

            return {**result, "bot_id": bot.bot_id, "workflow_run_id": workflow_run_id}

        except Exception as e:
            logger.error(
                f"Failed to resume searching for workflow run {workflow_run_id}: {e}"
            )
            return {
                "success": False,
                "message": f"Failed to resume searching: {str(e)}",
                "workflow_run_id": workflow_run_id,
            }

    def get_bot_status(self, workflow_run_id: str) -> Dict[str, Any]:
        """Get bot status for a workflow run"""
        if workflow_run_id not in self.bots:
            return {
                "workflow_run_id": workflow_run_id,
                "bot_exists": False,
                "message": "No bot found for this session",
            }

        bot = self.bots[workflow_run_id]
        status = bot.get_status()

        return {**status, "workflow_run_id": workflow_run_id, "bot_exists": True}

    def get_all_bots_status(self) -> Dict[str, Any]:
        """Get status of all bots"""
        statuses = {}
        for workflow_run_id, bot in self.bots.items():
            statuses[workflow_run_id] = bot.get_status()

        return {"total_bots": len(self.bots), "bots": statuses}

    def cleanup_session(self, workflow_run_id: str):
        """Cleanup all resources for a workflow run"""
        try:
            # Stop bot if exists and not already stopping
            if (
                workflow_run_id in self.bots
                and workflow_run_id not in self.stopping_sessions
            ):
                self.stop_searching_controller(workflow_run_id)

            # Unregister polling session
            self.unregister_polling_session(workflow_run_id)

            # Remove from stopping sessions if present
            self.stopping_sessions.discard(workflow_run_id)

            logger.info(f"Cleaned up workflow run: {workflow_run_id}")

        except Exception as e:
            logger.error(f"Failed to cleanup workflow run {workflow_run_id}: {e}")


# Global bot controller instance
dice_bot_controller = DiceBotController()
