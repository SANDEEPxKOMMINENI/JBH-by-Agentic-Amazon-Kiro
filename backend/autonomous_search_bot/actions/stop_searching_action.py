"""Stop Searching Action for Autonomous Search Bot."""

import asyncio
import logging

from autonomous_search_bot.actions.base_action import BaseAction

logger = logging.getLogger(__name__)


class StopSearchingAction(BaseAction):
    """Action to stop the autonomous job searching process"""

    def __init__(self, bot_instance):
        super().__init__(bot_instance)

    @property
    def action_name(self) -> str:
        return "stop_searching"

    def execute(self) -> None:
        """Stop the autonomous searching process"""
        try:
            self.logger.info(
                f"Stopping autonomous bot for session {self.bot.workflow_run_id}"
            )

            # Set stop flag
            self.bot._stop_requested = True

            # Schedule shutdown coroutine if loop exists
            if self.bot._loop:
                asyncio.run_coroutine_threadsafe(
                    self._shutdown_coroutine(), self.bot._loop
                )

        except Exception as exc:
            self.logger.exception("Failed to stop autonomous bot: %s", exc)

    async def _shutdown_coroutine(self) -> None:
        """Async shutdown - sends activity and shuts down browser"""
        if self.bot.activity_callback:
            try:
                self.bot.activity_callback(
                    {
                        "type": "action",
                        "message": "Stop requested – shutting down browser session...",
                    }
                )
            except Exception:
                logger.debug("Activity callback raised", exc_info=True)

        await self._graceful_browser_shutdown()

    async def _graceful_browser_shutdown(self) -> None:
        """Gracefully shut down the browser"""
        if self.bot.browser:
            try:
                await self.bot.browser.stop()
            except Exception:
                logger.debug("Browser shutdown raised, ignoring", exc_info=True)
            finally:
                self.bot.browser = None
