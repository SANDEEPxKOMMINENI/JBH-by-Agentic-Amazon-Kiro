"""
Playwright Wrapper - Async operation control with pause/resume functionality
Modern replacement for v1's PlaywrightWrapper, designed for async operations
"""

# import asyncio - removed for sync conversion
import logging
import random
import time
import traceback
from typing import Any, Callable, Optional

from browser.automation import Page  # noqa: E402

logger = logging.getLogger(__name__)


def check_page_wrapper(fn):
    """Decorator to check if page is not closed before operation"""

    def wrapped(self, *args, **kwargs):
        if not self.check_page_not_closed():
            logger.warning(f"Page closed: Skipping {fn.__name__}")
            return None
        return fn(self, *args, **kwargs)

    return wrapped


class PlaywrightWrapper:
    """
    Async wrapper for Playwright operations with speed control and
    pause/resume functionality. Designed to be inherited by browser
    operators and bots.
    """

    def __init__(
        self,
        pause_op: bool = False,
        avg_delay: float = 1.0,
        std_delay: float = 0.5,
        debug_mode: bool = False,
    ):
        self.pause_op = pause_op
        self.avg_delay = avg_delay if not debug_mode else 0
        self.std_delay = std_delay
        self.last_op_time = 0.0
        self.page: Optional[Page] = None
        self.debug_mode = debug_mode

        # Callback mechanism for UI updates (to be set by implementing classes)
        self.status_callback: Optional[Callable] = None
        self.activity_callback: Optional[Callable] = None

        # Bot reference for stop signal detection
        self.bot_instance = None

        # Flag to prevent duplicate Cloudflare notifications
        self.cloudflare_notified = False

    def op(self, fn: Callable, ignore_exception: bool = False, **kwargs) -> Any:
        """
        Execute an operation with speed control and pause/resume functionality

        Args:
            fn: The sync function to execute
            ignore_exception: Whether to suppress exceptions
            **kwargs: Arguments to pass to the function

        Returns:
            Result of the function execution
        """
        try:
            # Check if browser/page is still available before operation
            if not self._maybe_close_playwright():
                if ignore_exception:
                    return None
                raise Exception("Playwright/Browser is closed or unavailable")

            self._sleep_if_operating_fast()
            # self._maybe_pause_due_to_human_interaction()

            # Wait while paused
            while self.pause_op:
                self._pause_browser()
                time.sleep(1)

            self._resume_browser()
            result = fn(**kwargs)
            # self._reset_human_touched_flag_on_browser()
            self.last_op_time = time.time()

            # Check for Cloudflare challenge after operation completes
            if self._detect_and_handle_cloudflare():
                logger.info("Cloudflare challenge detected after operation")
                if ignore_exception:
                    return None
                raise Exception("Cloudflare challenge detected")

            return result

        except Exception as e:
            if ignore_exception:
                return None
            logger.error(f"Playwright Wrapper Error: {e}")
            logger.error(traceback.format_exc())
            raise e

    def click_with_op(self, locator, **click_kwargs) -> None:
        """Wrapper for clicking with operation control"""

        def click_fn():
            return locator.click(**click_kwargs)

        logger.debug(f"🖱Clicking element: {locator}")
        return self.op(click_fn)

    def click_with_mouse_op(self, locator, **mouse_click_kwargs) -> None:
        """Wrapper for clicking using mouse after locating element with operation control"""

        def mouse_click_fn():
            if not self.page:
                raise Exception("Page not available for mouse click")

            # Get bounding box of the locator
            bounding_box = locator.bounding_box()
            if not bounding_box:
                raise Exception(f"Could not get bounding box for locator: {locator}")

            # Calculate center coordinates
            center_x = bounding_box["x"] + bounding_box["width"] / 2
            center_y = bounding_box["y"] + bounding_box["height"] / 2

            # Move mouse to center of element
            self.page.mouse.move(center_x, center_y, steps=random.randint(5, 15))

            # Small delay to simulate human behavior
            time.sleep(random.uniform(0.05, 0.15))

            # Click using mouse
            self.page.mouse.click(center_x, center_y, **mouse_click_kwargs)

            return None

        logger.debug(f"🖱Clicking element with mouse: {locator}")
        return self.op(mouse_click_fn)

    def fill_with_op(self, locator, value: str, **fill_kwargs) -> None:
        """Wrapper for filling text with operation control"""

        def fill_fn():
            return locator.fill(value, **fill_kwargs)

        logger.debug(f"⌨Filling text: '{value[:50]}...' into {locator}")
        return self.op(fill_fn)

    def type_with_op(self, locator, text: str, **type_kwargs) -> None:
        """Wrapper for typing text with operation control"""

        def type_fn():
            return locator.type(text, **type_kwargs)

        logger.debug(f"⌨Typing text: '{text[:50]}...' into {locator}")
        return self.op(type_fn)

    def select_option_with_op(self, locator, **select_kwargs) -> None:
        """Wrapper for selecting options with operation control"""

        def select_fn():
            return locator.select_option(**select_kwargs)

        logger.debug(f"🔽 Selecting option in {locator}")
        return self.op(select_fn)

    def set_input_files_with_op(self, locator, files, **kwargs) -> None:
        """Wrapper for setting input files with operation control"""

        def set_files_fn():
            return locator.set_input_files(files, **kwargs)

        logger.debug(f"Setting input files: {files} on {locator}")
        return self.op(set_files_fn)

    def scroll_with_op(self, delta_x: int = 0, delta_y: int = 1000) -> None:
        """Wrapper for scrolling with operation control"""

        def scroll_fn():
            if not self.page:
                return None
            return self.page.mouse.wheel(delta_x=delta_x, delta_y=delta_y)

        logger.debug(f"📜 Scrolling: delta_x={delta_x}, delta_y={delta_y}")
        return self.op(scroll_fn)

    def scroll_slowly_to_bottom(self, delta_y: int = 1000, delay: float = 0.1) -> None:
        """
        Scroll down slowly by a fixed amount with delay.

        Args:
            delta_y: Amount to scroll down in pixels
            delay: Delay after scroll in seconds
        """
        self.scroll_with_op(delta_x=0, delta_y=delta_y)
        time.sleep(delay)

    def scroll_into_view_with_op(self, locator, sleep_after: float = 5.0) -> None:
        """
        Scroll element into view if needed and wait for rendering.

        Args:
            locator: Playwright locator to scroll into view
            sleep_after: Time to sleep after scrolling (default: 5 seconds)
        """

        def scroll_fn():
            locator.scroll_into_view_if_needed()
            return None

        logger.debug(
            f"📜 Scrolling element into view: {locator} " f"(sleep: {sleep_after}s)"
        )
        self.op(scroll_fn)
        time.sleep(sleep_after)

    def scroll_page_gradually(
        self,
        total_height: int | None = None,
        steps: int | None = None,
        min_delay: float = 0.1,
        max_delay: float = 0.3,
    ) -> None:
        """
        Scroll through entire page gradually with random delays.

        Args:
            total_height: Total height to scroll (auto-detected if None)
            steps: Number of scroll steps (calculated if None)
            min_delay: Minimum delay between scrolls
            max_delay: Maximum delay between scrolls
        """
        if not self.page:
            return

        # Auto-detect total height if not provided
        if total_height is None:
            try:
                body_box = self.page.locator("body").bounding_box()
                total_height = body_box.get("height", 2000) if body_box else 2000
            except Exception as e:
                logger.debug(f"Could not detect page height: {e}")
                total_height = 2000

        # Calculate steps if not provided
        delta_y = 800
        if steps is None:
            steps = int(total_height // delta_y + 1)

        scroll_amount = total_height / steps
        logger.debug(
            f"📜 Scrolling gradually: {steps} steps, " f"{scroll_amount:.1f}px per step"
        )

        for i in range(steps):
            self.scroll_with_op(delta_x=0, delta_y=int(scroll_amount))
            # Random delay like human behavior
            delay = random.uniform(min_delay, max_delay)
            time.sleep(delay)

    def _sleep_if_operating_fast(self):
        """Add delay if operations are happening too fast"""
        if self.debug_mode:
            return

        # Follow normal distribution and ensure positive value
        min_interval = max(0, random.normalvariate(self.avg_delay, self.std_delay))
        current_time = time.time()
        sleep_time = self.last_op_time + min_interval - current_time

        if sleep_time > 0:
            logger.debug(f"⏱Sleeping for {sleep_time:.2f}s to control operation speed")
            time.sleep(sleep_time)

    @check_page_wrapper
    def pause(self):
        """Pause all operations"""
        logger.info("⏸Pausing operations...")
        self.pause_op = True
        if self.status_callback:
            self.status_callback("paused", "Operations paused by user")

    @check_page_wrapper
    def resume(self):
        """Resume all operations"""
        logger.info("▶Resuming operations...")
        self.pause_op = False
        if self.status_callback:
            self.status_callback("running", "Operations resumed")

    @check_page_wrapper
    def _pause_browser(self):
        """Signal browser that operations are paused"""
        if self.page and hasattr(self.page, "evaluate"):
            try:
                self.page.evaluate("window.dispatchEvent(new Event('pause_event'))")
            except Exception as e:
                logger.debug(f"Could not signal pause to browser: {e}")

    @check_page_wrapper
    def _resume_browser(self):
        """Signal browser that operations are resumed"""
        if self.page and hasattr(self.page, "evaluate"):
            try:
                self.page.evaluate("window.dispatchEvent(new Event('playwright-bot'))")
            except Exception as e:
                logger.debug(f"Could not signal resume to browser: {e}")

    @check_page_wrapper
    def _reset_human_touched_flag_on_browser(self):
        """Reset the human interaction flag in browser"""
        if not self.page:
            return

        try:
            self.page.evaluate("window.dispatchEvent(new Event('playwright-bot'))")
        except Exception as e:
            logger.debug(f"Error resetting human touched flag: {e}")

    @check_page_wrapper
    def _maybe_pause_due_to_human_interaction(self):
        """Check for human interaction and pause if detected"""
        if not self.page:
            return

        try:
            browser_human_touched = self.page.evaluate("window.__human_touched")
            if browser_human_touched:
                logger.info("👤 Human interaction detected, pausing operations...")
                if self.activity_callback:
                    self.activity_callback(
                        "Human interaction detected, pausing operations..."
                    )
                self.pause_op = True
                if self.status_callback:
                    self.status_callback("paused", "Paused due to human interaction")
        except Exception as e:
            logger.debug(f"Error checking human interaction: {e}")

    def check_page_not_closed(self) -> bool:
        """Check if page is available and not closed"""
        if self.page is None:
            return False

        try:
            if self.page.is_closed():
                logger.info("Page is closed")
                return False
        except Exception as e:
            logger.debug(f"Error checking page status: {e}")
            return False

        return True

    def set_page(self, page: Page):
        """Set the page reference for operations"""
        self.page = page

    def set_callbacks(
        self,
        status_callback: Optional[Callable] = None,
        activity_callback: Optional[Callable] = None,
    ):
        """Set callback functions for status and activity updates"""
        self.status_callback = status_callback
        self.activity_callback = activity_callback

    def set_bot_instance(self, bot_instance):
        """Set the bot instance for stop signal detection"""
        self.bot_instance = bot_instance

    def graceful_shutdown(self):
        """Initiate graceful shutdown when stop signal is detected"""
        logger.info("Graceful shutdown initiated due to stop signal")

        # Mark as no longer available for operations
        self.page = None

        # If we have a bot instance, trigger its graceful shutdown
        if self.bot_instance and hasattr(self.bot_instance, "browser_operator"):
            try:
                # This will trigger the graceful close method we just updated
                if self.bot_instance.browser_operator:
                    self.bot_instance.browser_operator.close()
            except Exception as e:
                logger.debug(f"Error during graceful shutdown: {e}")

        logger.info("Graceful shutdown completed")

    def _handle_manual_browser_close(self):
        """Handle cases where the browser was closed manually by the user"""
        logger.info("🖱Browser was closed manually - initiating cleanup")

        # Clear page reference immediately
        self.page = None

        # If we have a bot instance, update its status and trigger cleanup
        if self.bot_instance:
            try:
                # Mark bot as stopped since browser is no longer available
                self.bot_instance.is_running = False
                self.bot_instance.status = "stopped"

                # Clear bot's page reference
                self.bot_instance.page = None

                # Trigger graceful cleanup of remaining browser resources
                if (
                    hasattr(self.bot_instance, "browser_operator")
                    and self.bot_instance.browser_operator
                ):
                    try:
                        # This will clean up context, browser, and playwright references
                        self.bot_instance.browser_operator.close()
                    except Exception as e:
                        logger.debug(f"Error during manual close cleanup: {e}")

                logger.info("Manual browser close handled gracefully")

                # Notify via callback if available
                if self.activity_callback:
                    self.activity_callback("🖱Browser was closed manually - bot stopped")

            except Exception as e:
                logger.debug(f"Error handling manual browser close: {e}")

    def _detect_and_handle_cloudflare(self) -> bool:
        """
        Detect Cloudflare challenge in shadow DOM and handle gracefully.

        Returns:
            True if Cloudflare detected and handled,
            False if no Cloudflare or detection failed
        """
        try:
            if not self.page or self.page.is_closed():
                return False

            # Simple and direct: Check for Cloudflare troubleshooting link
            # This is a definitive indicator that Cloudflare challenge is present
            has_cloudflare = False

            try:
                # Check for the Cloudflare troubleshooting link
                troubleshooting_link = self.page.locator("a#troubleshooting")
                if troubleshooting_link.count() > 0:
                    href = troubleshooting_link.get_attribute("href")
                    if href and "Troubleshooting-Cloudflare-Errors" in href:
                        has_cloudflare = True
                        logger.warning(
                            f"Cloudflare challenge detected via troubleshooting link: {href}"
                        )
            except Exception as e:
                logger.debug(f"Error checking for Cloudflare troubleshooting link: {e}")
                # If check fails, assume no Cloudflare (fail-safe)

            try:
                # Check for Glassdoor-specific Cloudflare message
                article_div = self.page.locator("div[class*=article]").first
                if article_div.count() > 0:
                    inner_text = article_div.inner_text()
                    if inner_text and "Help Us Protect Glassdoor" in inner_text:
                        has_cloudflare = True
                        logger.warning(
                            "Cloudflare challenge detected via Glassdoor protection message"
                        )
            except Exception as e:
                logger.debug(f"Error checking for Glassdoor protection message: {e}")
                # If check fails, assume no Cloudflare (fail-safe)

            # If Cloudflare detected, handle it
            if has_cloudflare:
                # Only send notifications once (prevent duplicate messages)
                if not self.cloudflare_notified:
                    logger.warning(
                        "Cloudflare challenge detected, stopping bot gracefully"
                    )

                    cloudflare_message = (
                        "Detected Cloudflare verification challenge. "
                        "Please use the 'Sign In' button to bypass the verification and try again."
                    )

                    # Send both activity message AND status update
                    # Activity callback - for run page activity log
                    if self.activity_callback:
                        logger.info(
                            "Sending Cloudflare notification via activity callback"
                        )
                        try:
                            self.activity_callback(cloudflare_message)
                            logger.info(
                                "Cloudflare activity notification sent successfully"
                            )
                        except Exception as e:
                            logger.error(
                                f"Failed to send Cloudflare activity notification: {e}"
                            )
                    else:
                        logger.warning("No activity_callback set")

                    # Status callback - for infinite hunt session status
                    if self.status_callback:
                        logger.info("Sending Cloudflare status update")
                        try:
                            self.status_callback("error", cloudflare_message)
                            logger.info("Cloudflare status update sent successfully")
                        except Exception as e:
                            logger.error(
                                f"Failed to send Cloudflare status update: {e}"
                            )
                    else:
                        logger.warning("No status_callback set")

                    # Update bot status - this will cause operations to stop
                    if self.bot_instance:
                        try:
                            self.bot_instance.is_running = False
                            self.bot_instance.status = "stopped"
                            # Set verification_required flag for infinite hunt manager
                            self.bot_instance.verification_required = True
                            logger.info(
                                "Bot status set to stopped due to Cloudflare challenge. "
                                "verification_required=True"
                            )
                        except Exception as e:
                            logger.debug(f"Error updating bot status: {e}")

                    # Mark as notified to prevent duplicate notifications
                    self.cloudflare_notified = True

                # Don't call graceful_shutdown() here - let the bot handle cleanup
                # The bot will see is_running=False and stop naturally
                # Setting page to None will cause _maybe_close_playwright to return False
                self.page = None
                return True

            return False

        except Exception as e:
            logger.debug(f"Error detecting Cloudflare challenge: {e}")
            return False

    def _maybe_close_playwright(self) -> bool:
        """
        Check if Playwright/browser is still available and handle cleanup if needed.
        Also detects stop signals from the bot controller.

        Returns:
            True if browser is available for operations,
            False if closed/unavailable/stopping
        """
        try:
            # Check for stop signals from bot - this is the key enhancement!
            if self.bot_instance:
                # Check if bot is being stopped or has stopped
                if not getattr(self.bot_instance, "is_running", True):
                    logger.debug(
                        "Bot is not running - stop signal detected, "
                        "initiating graceful shutdown"
                    )
                    # Don't call graceful_shutdown here to avoid recursion
                    return False

                bot_status = getattr(self.bot_instance, "status", "unknown")
                if bot_status in ["stopping", "stopped", "error"]:
                    logger.debug(
                        f"Bot status is '{bot_status}' - stop signal "
                        "detected, operations will cease"
                    )
                    return False

            # Check if page exists and is not closed
            if not self.page:
                self._handle_manual_browser_close()
                return False

            # Check if page is closed (user closed browser manually)
            try:
                if self.page.is_closed():
                    self._handle_manual_browser_close()
                    return False
            except Exception as e:
                logger.debug(f"Error checking if page is closed: {e}")
                self._handle_manual_browser_close()
                return False

            # Try a simple operation to verify page is responsive
            try:
                # This should be fast and not cause side effects
                self.page.url
            except Exception as e:
                logger.debug(f"Page is unresponsive (likely closed manually): {e}")
                self._handle_manual_browser_close()
                return False

            return True

        except Exception as e:
            logger.debug(f"Error checking Playwright state: {e}")
            # On any error, assume browser is closed manually
            self._handle_manual_browser_close()
            return False

    def is_paused(self) -> bool:
        """Check if operations are currently paused"""
        return self.pause_op

    def wait_if_paused(self, check_interval: float = 1.0):
        """Wait while operations are paused"""
        while self.pause_op:
            time.sleep(check_interval)
