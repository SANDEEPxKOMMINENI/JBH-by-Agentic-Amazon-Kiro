#!/usr/bin/env python3
"""
Stop Searching Action for Dice Bot
"""

import logging
from typing import Any, Dict

from dice_bot.actions.base_action import BaseAction

logger = logging.getLogger(__name__)


class StopSearchingAction(BaseAction):
    """Action to stop the Dice searching process"""

    @property
    def action_name(self) -> str:
        return "stop_searching"

    def execute(self) -> Dict[str, Any]:
        """
        Stop the Dice searching process, close browser, and eliminate bot
        """
        try:
            self.logger.info(f"Stopping Dice bot {self.bot.bot_id}")

            self.send_status_update("stopping", "Stopping bot and closing browser...")

            # Mark as not running immediately to stop any ongoing operations
            self.bot.is_running = False
            self.bot.status = "stopping"

            # Close browser resources completely
            self._close_browser_completely()

            # Clear all bot state
            self._clear_bot_state()

            # Verify cleanup was successful
            self._verify_cleanup()

            # Final status update
            self.bot.status = "stopped"
            self.send_status_update("stopped", "Bot stopped and browser closed")
            self.send_activity_message("Bot process terminated successfully")

            self.logger.info(f"Dice bot {self.bot.bot_id} stopped and eliminated")

            return {
                "success": True,
                "message": "Dice bot stopped and browser eliminated",
                "status": "stopped",
            }

        except Exception as e:
            self.logger.error(f"Failed to stop Dice bot: {e}")

            # Force cleanup
            self._force_cleanup()

            return {
                "success": False,
                "message": f"Error stopping bot: {str(e)}",
                "status": "error",
            }

    def _close_browser_completely(self):
        """Gracefully close browser operator and all resources"""
        if self.bot.browser_operator:
            try:
                self.logger.info("Gracefully closing browser operator")
                self.bot.browser_operator.close()

                # Brief pause to allow graceful shutdown
                import time

                time.sleep(1)

                self.send_activity_message("Browser closed gracefully")
                self.logger.info("Browser operator closed gracefully")
            except Exception as e:
                self.logger.error(f"Error during graceful browser close: {e}")
                self.send_activity_message(f"Warning: Browser close error: {str(e)}")
        return True

    def _clear_bot_state(self):
        """Clear all bot state and references"""
        self.logger.info("Clearing bot state")

        # Clear browser references
        self.bot.page = None
        self.bot.current_url = ""

        # Clear any other state
        if hasattr(self.bot, "workflow_run_id"):
            self.bot.workflow_run_id = None

    def _force_cleanup(self):
        """Force cleanup on error - best effort cleanup"""
        self.logger.info("Force cleanup initiated")

        self.bot.is_running = False
        self.bot.status = "error"

        try:
            self._close_browser_completely()
        except Exception as e:
            self.logger.error(f"Force cleanup browser error: {e}")

        try:
            self._clear_bot_state()
        except Exception as e:
            self.logger.error(f"Force cleanup state error: {e}")

        self.send_activity_message("Force cleanup completed - bot terminated")

    def _verify_cleanup(self):
        """Verify that browser processes have been terminated"""
        try:
            import platform
            import subprocess

            system = platform.system().lower()

            if system == "darwin":  # macOS
                # Check for remaining Chromium processes
                result = subprocess.run(
                    ["pgrep", "-f", "chromium"],
                    capture_output=True,
                    text=True,
                    check=False,
                )

                if result.returncode == 0 and result.stdout.strip():
                    self.logger.warning(
                        f"Found remaining Chromium processes: {result.stdout.strip()}"
                    )
                    self.send_activity_message(
                        "Some browser processes may still be running"
                    )
                else:
                    self.logger.info("No remaining Chromium processes found")

            elif system == "linux":
                # Check for remaining Chromium processes
                result = subprocess.run(
                    ["pgrep", "-f", "chromium"],
                    capture_output=True,
                    text=True,
                    check=False,
                )

                if result.returncode == 0 and result.stdout.strip():
                    self.logger.warning(
                        f"Found remaining Chromium processes: {result.stdout.strip()}"
                    )
                    self.send_activity_message(
                        "Some browser processes may still be running"
                    )
                else:
                    self.logger.info("No remaining Chromium processes found")

            elif system == "windows":
                # Check for remaining Chromium processes
                result = subprocess.run(
                    ["tasklist", "/FI", "IMAGENAME eq chromium.exe"],
                    capture_output=True,
                    text=True,
                    check=False,
                )

                if "chromium.exe" in result.stdout:
                    self.logger.warning("Found remaining Chromium processes")
                    self.send_activity_message(
                        "Some browser processes may still be running"
                    )
                else:
                    self.logger.info("No remaining Chromium processes found")

        except Exception as e:
            self.logger.debug(f"Could not verify process cleanup: {e}")
