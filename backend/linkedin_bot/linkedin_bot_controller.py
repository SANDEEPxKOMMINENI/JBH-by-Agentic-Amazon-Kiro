#!/usr/bin/env python3
"""
LinkedIn Bot Controller for JobHuntr v2
@file purpose: Manage LinkedIn bot instances and WebSocket communication
"""

import logging
import os
import queue
import sys
import threading
import uuid  # noqa: E402
from threading import Lock  # noqa: E402
from typing import Any, Dict, List, Optional  # noqa: E402

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from linkedin_bot.linkedin_bot import LinkedInBot  # noqa: E402

logger = logging.getLogger(__name__)


class LinkedInBotController:
    """Controller to manage LinkedIn bot instances and activity polling"""

    def __init__(self):
        self.bots: Dict[str, LinkedInBot] = {}
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
                    f"Trimmed activity queue for workflow run {workflow_run_id} to {MAX_MESSAGES_PER_WORKFLOW_RUN} messages"  # noqa: E501
                )

            logger.debug(
                f"Stored activity message for workflow run {workflow_run_id}: {message.get('message', 'No message')}"  # noqa: E501
            )

    def start_hunting_controller(
        self,
        user_id: str,
        workflow_run_id: str,
        bot_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Start hunting for a workflow run
        """
        try:
            # Check if bot already exists for this workflow run
            if workflow_run_id in self.bots:
                bot = self.bots[workflow_run_id]
                if bot.is_running:
                    return {
                        "success": False,
                        "message": "Bot is already running for this workflow/session",
                        "bot_id": bot.bot_id,
                    }
                else:
                    # Remove stopped bot and create new one
                    del self.bots[workflow_run_id]

            # Create callback function for this workflow run
            def activity_callback(message):
                self._send_activity_message(workflow_run_id, message)

            logger.info(f"Using workflow run ID: {workflow_run_id}")

            # Create new bot with callback and workflow run ID
            bot_id = f"linkedin_bot_{workflow_run_id}_{uuid.uuid4().hex[:8]}"
            bot = LinkedInBot(
                bot_id,
                user_id,
                websocket_callback=activity_callback,
                workflow_run_id=workflow_run_id,
            )
            # Store bot using workflow_run_id
            self.bots[workflow_run_id] = bot
            logger.info(
                f"Created new LinkedIn bot for workflow run {workflow_run_id}: {bot_id}"
            )

            # Start the bot with pre-constructed LinkedIn URL
            linkedin_starter_url = None
            if bot_config and "linkedinStarterUrl" in bot_config:
                linkedin_starter_url = bot_config["linkedinStarterUrl"]
                logger.info(
                    f"Using pre-constructed LinkedIn URL: {linkedin_starter_url}"
                )

            # Run bot operations in a separate thread to avoid async/sync conflicts
            def run_bot_in_thread():
                try:
                    logger.info(f"Starting bot thread for {workflow_run_id}")
                    result = bot.start_hunting(linkedin_starter_url)
                    logger.info(f"Bot thread completed for {workflow_run_id}: {result}")

                    # If bot failed, clean it up
                    if not result.get("success", False):
                        logger.error(f"Bot failed for {workflow_run_id}, cleaning up")
                        if workflow_run_id in self.bots:
                            del self.bots[workflow_run_id]
                        self._send_activity_message(
                            workflow_run_id,
                            {
                                "type": "error",
                                "message": f"Bot failed: {result.get('message', 'Unknown error')}",  # noqa: E501
                            },
                        )
                except Exception as e:
                    logger.error(f"Bot thread error for {workflow_run_id}: {e}")
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
                f"Failed to start hunting for workflow run {workflow_run_id}: {e}"
            )

            # Cleanup on error
            if workflow_run_id in self.bots:
                del self.bots[workflow_run_id]

            self._send_activity_message(
                workflow_run_id,
                {"type": "error", "message": f"Failed to start hunting: {str(e)}"},
            )

            return {
                "success": False,
                "message": f"Failed to start hunting: {str(e)}",
                "workflow_run_id": workflow_run_id,
            }

    def stop_hunting_controller(self, workflow_run_id: str) -> Dict[str, Any]:
        """Stop hunting for a workflow run"""
        try:
            logger.info(f"Stop requested for workflow_run_id: {workflow_run_id}")
            logger.info(f"Available bot keys: {list(self.bots.keys())}")

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
                logger.warning(
                    f"No bot found for workflow_run_id: {workflow_run_id}. Available keys: {list(self.bots.keys())}"
                )
                return {
                    "success": False,
                    "message": "No active bot found for this workflow run",
                    "workflow_run_id": workflow_run_id,
                }

            # Mark workflow run as being stopped
            self.stopping_sessions.add(workflow_run_id)

            bot = self.bots[workflow_run_id]
            bot_id = bot.bot_id

            logger.info(f"Stopping bot {bot_id} for workflow run {workflow_run_id}")

            # CRITICAL: Set is_running to False IMMEDIATELY before spawning stop thread
            # This ensures the main bot thread sees the stop signal right away
            logger.info(
                f"Before stop - bot.is_running={bot.is_running}, bot id={id(bot)}"
            )
            bot.is_running = False
            bot.status = "stopping"
            logger.info(
                f"After stop - bot.is_running={bot.is_running}, bot id={id(bot)}"
            )

            # Run bot stop operation in a separate thread to avoid async/sync conflicts
            result_queue = queue.Queue()

            def run_stop_in_thread():
                try:
                    result = bot.stop_hunting()
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

            # Clean up workflow run data to prevent memory leaks
            self.cleanup_session_data(workflow_run_id)

            # Remove from stopping sessions
            self.stopping_sessions.discard(workflow_run_id)

            logger.info(
                f"Bot {bot_id} completely removed from workflow run {workflow_run_id}"
            )  # noqa: E402

            return {**result, "bot_id": bot_id, "workflow_run_id": workflow_run_id}

        except Exception as e:
            logger.error(
                f"Failed to stop hunting for workflow run {workflow_run_id}: {e}"
            )

            # Force cleanup
            if workflow_run_id in self.bots:
                del self.bots[workflow_run_id]

            # Clean up workflow run data even on error
            self.cleanup_session_data(workflow_run_id)
            self.stopping_sessions.discard(workflow_run_id)

            self._send_activity_message(
                workflow_run_id,
                {"type": "error", "message": f"Failed to stop hunting: {str(e)}"},
            )

            logger.info(f"🚨 Force cleanup completed for workflow run {workflow_run_id}")

            return {
                "success": False,
                "message": f"Failed to stop hunting: {str(e)}",
                "workflow_run_id": workflow_run_id,
            }

    def pause_hunting_controller(self, workflow_run_id: str) -> Dict[str, Any]:
        """Pause hunting for a workflow run"""
        try:
            if workflow_run_id not in self.bots:
                return {
                    "success": False,
                    "message": "No active bot found for this workflow run",
                    "workflow_run_id": workflow_run_id,
                }

            bot = self.bots[workflow_run_id]

            result = bot.pause_hunting()

            return {**result, "bot_id": bot.bot_id, "workflow_run_id": workflow_run_id}

        except Exception as e:
            logger.error(
                f"Failed to pause hunting for workflow run {workflow_run_id}: {e}"
            )
            return {
                "success": False,
                "message": f"Failed to pause hunting: {str(e)}",
                "workflow_run_id": workflow_run_id,
            }

    def resume_hunting_controller(self, workflow_run_id: str) -> Dict[str, Any]:
        """Resume hunting for a workflow run"""
        try:
            if workflow_run_id not in self.bots:
                return {
                    "success": False,
                    "message": "No active bot found for this workflow run",
                    "workflow_run_id": workflow_run_id,
                }

            bot = self.bots[workflow_run_id]

            result = bot.resume_hunting()

            return {**result, "bot_id": bot.bot_id, "workflow_run_id": workflow_run_id}

        except Exception as e:
            logger.error(
                f"Failed to resume hunting for workflow run {workflow_run_id}: {e}"
            )
            return {
                "success": False,
                "message": f"Failed to resume hunting: {str(e)}",
                "workflow_run_id": workflow_run_id,
            }

    def get_bot_status(self, workflow_run_id: str) -> Dict[str, Any]:
        """Get bot status for a session"""
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

    def collect_contacts_controller(
        self, application_history_list: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """
        Collect contacts from LinkedIn job applications  # noqa: E402

        Args:
            application_history_list: List of application history records
                (must contain user_id and workflow_run_id)

        Returns:
            Dict containing success status and collected contacts
        """
        try:
            from linkedin_bot.actions.collect_contacts_action import (  # noqa: E402
                CollectContactsAction,
            )

            logger.info(
                f"Starting contact collection for {len(application_history_list)} applications"  # noqa: E501
            )

            # Run action in a separate thread to avoid async/sync conflicts
            def run_action_in_thread():
                try:
                    # Create a mock bot instance for the action
                    bot_instance = type(
                        "MockBot",
                        (),
                        {
                            "websocket_callback": None,
                            "bot_id": "contact_collector",
                            "is_running": True,
                        },
                    )()

                    # Store bot instance for stopping
                    self.bots["contact_collector"] = bot_instance
                    logger.info("Bot instance stored for stopping")

                    # Fetch existing contacts from database
                    from services.supabase_client import supabase_client  # noqa: E402

                    existing_contacts = supabase_client.get_contacts() or []
                    logger.info(f"Loaded {len(existing_contacts)} existing contacts")

                    # Create and execute the action
                    # user_id and workflow_run_id will be extracted
                    # from application_history_list
                    action = CollectContactsAction(bot_instance, existing_contacts)
                    result = action.execute(application_history_list)

                    logger.info(
                        "Contact collection completed: "
                        f"{result.get('processed_count', 0)} applications processed"
                    )

                    # Clean up bot instance after completion
                    self.bots.pop("contact_collector", None)
                    logger.info("Bot instance cleaned up")

                except Exception as e:
                    logger.error(f"Contact collection thread error: {e}")
                    # Clean up bot instance on error
                    self.bots.pop("contact_collector", None)

            # Start the action in a separate thread (non-blocking)
            action_thread = threading.Thread(target=run_action_in_thread, daemon=True)
            action_thread.start()

            # Return immediately - don't wait for completion
            logger.info("Contact collection started in background thread")

            return {
                "success": True,
                "message": "Contact collection started",
                "contacts": [],
                "processed_count": 0,
            }

        except Exception as e:
            logger.error(f"Failed to collect contacts: {e}")
            return {
                "success": False,
                "error": f"Failed to collect contacts: {str(e)}",
                "contacts": [],
                "processed_count": 0,
            }

    def stop_collection_controller(self) -> dict[str, Any]:
        """
        Stop the ongoing contact collection process

        Returns:
            Dict containing success status and message
        """
        try:
            logger.info("Stopping contact collection")
            logger.info(f"Current bots: {list(self.bots.keys())}")

            # Find the active bot running collection
            bot = self.bots.get("contact_collector")
            if bot:
                logger.info(
                    "Found bot instance, current is_running: "
                    f"{getattr(bot, 'is_running', 'N/A')}"
                )
                # Set stop flag using the shared is_running flag
                bot.is_running = False
                logger.info("Stop signal sent to collection bot")
                return {"success": True, "message": "Contact collection stop requested"}
            else:
                logger.warning(
                    "No active collection bot found. Available bots: "
                    f"{list(self.bots.keys())}"
                )
                return {
                    "success": False,
                    "message": "No active contact collection in progress",
                }

        except Exception as e:
            logger.error(f"Failed to stop collection: {e}")
            return {"success": False, "message": f"Failed to stop collection: {str(e)}"}

    def connect_contacts_controller(
        self,
        contacts: list[dict[str, Any]],
        message_template: str | None = None,
        use_individual_messages: bool = False,
    ) -> dict[str, Any]:
        """
        Start connecting to contacts with optional message.

        Args:
            contacts: List of contact dictionaries
            message_template: Optional message template with {first_name} placeholder
            use_individual_messages: If True, use each contact's individual message

        Returns:
            Dict containing success status and message
        """
        try:
            from linkedin_bot.actions.connect_contacts_action import (  # noqa: E402
                ConnectContactsAction,
            )

            logger.info(f"Starting connection to {len(contacts)} contacts")

            # Create a bot instance
            bot_id = str(uuid.uuid4())
            # Use a generic user_id since this is a background task
            user_id = "system_connector"
            bot_instance = LinkedInBot(bot_id, user_id)
            bot_instance.is_running = True

            # Run connection in a separate thread (non-blocking)
            def run_action_in_thread():
                try:
                    # Store bot instance for stop signal
                    self.bots["contact_connector"] = bot_instance
                    logger.info("Stored bot instance: contact_connector")
                    logger.info(f"Bot instance is_running: {bot_instance.is_running}")

                    action = ConnectContactsAction(
                        bot_instance,
                        message_template=message_template,
                        use_individual_messages=use_individual_messages,
                    )
                    result = action.execute(contacts)
                    logger.info(f"Contact connection completed: {result}")
                except Exception as e:
                    logger.error(f"Connection action failed: {e}")
                    import traceback  # noqa: E402

                    traceback.print_exc()
                finally:
                    # Clean up bot instance after connection completes
                    if "contact_connector" in self.bots:
                        del self.bots["contact_connector"]
                        logger.info("Bot instance cleaned up")

            thread = threading.Thread(target=run_action_in_thread, daemon=True)
            thread.start()

            return {
                "success": True,
                "message": "Contact connection started",
                "contacts_count": len(contacts),
            }

        except Exception as e:
            logger.error(f"Failed to start contact connection: {e}")
            return {
                "success": False,
                "message": f"Failed to start connection: {str(e)}",
                "contacts_count": 0,
            }

    def stop_connect_controller(self) -> dict[str, Any]:
        """
        Stop the ongoing contact connection process

        Returns:
            Dict containing success status and message
        """
        try:
            logger.info("Stopping contact connection")
            logger.info(f"Current bots: {list(self.bots.keys())}")

            # Find the active bot running connection
            bot = self.bots.get("contact_connector")
            if bot:
                logger.info(
                    "Found bot instance, current is_running: "
                    f"{getattr(bot, 'is_running', 'N/A')}"
                )
                # Set stop flag
                bot.is_running = False
                logger.info("Stop signal sent to connection bot")
                return {"success": True, "message": "Contact connection stop requested"}
            else:
                logger.warning(
                    "No active connection bot found. Available bots: "
                    f"{list(self.bots.keys())}"
                )
                return {
                    "success": False,
                    "message": "No active contact connection in progress",
                }

        except Exception as e:
            logger.error(f"Failed to stop connection: {e}")
            return {"success": False, "message": f"Failed to stop connection: {str(e)}"}

    def cleanup_session(self, workflow_run_id: str):
        """Cleanup all resources for a session"""
        try:
            # Stop bot if exists and not already stopping
            if (
                workflow_run_id in self.bots
                and workflow_run_id not in self.stopping_sessions
            ):
                self.stop_hunting_controller(workflow_run_id)

            # Unregister polling session
            self.unregister_polling_session(workflow_run_id)

            # Remove from stopping sessions if present
            self.stopping_sessions.discard(workflow_run_id)

            logger.info(f"Cleaned up session: {workflow_run_id}")

        except Exception as e:
            logger.error(f"Failed to cleanup session {workflow_run_id}: {e}")


# Global bot controller instance
linkedin_bot_controller = LinkedInBotController()
