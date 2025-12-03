import logging
import os
import random
import sys
import time

from browser.automation import Browser, BrowserContext, Page

# from werkzeug.datastructures import FileStorage  # Not needed in v2


sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from constants import BOT_STATE_FILE, LOG_DIR, OBJECTS_DIR  # noqa: E402

logger = logging.getLogger(__name__)


class BrowserSession:
    """
    Browser session for bots (LinkedIn, Indeed, etc.)
    """

    def __init__(
        self,
        playwright,
        op,
        headless=False,
        state_path=BOT_STATE_FILE,
    ):
        self.p = playwright
        self.op = op
        self.headless = headless
        self.browser: Browser = None
        self.context: BrowserContext = None
        self.is_persistent = False
        self.state_path = state_path
        self.screenshot_folder_path = os.path.join(LOG_DIR, "screenshots")
        if not os.path.exists(self.screenshot_folder_path):
            os.makedirs(self.screenshot_folder_path)

    def _get_optimized_browser_args(self):
        """
        Get optimized browser arguments for better performance
        with bundled Chromium
        """
        return [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-features=VizDisplayCompositor",
            "--max_old_space_size=4096",
            "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding",
            "--disable-extensions",
            "--disable-plugins",
            "--disable-default-apps",
            "--disable-sync",
        ]

    def get_context(self) -> BrowserContext:
        """
        always try to get state from state_path  # noqa: E402
        if not, check if user has a profile and use persistent context
        if a user doesn't have a state path and doesn't have a profile,
        create a new browser context. A new browser context will be
        created when a user login for the first time.
        """
        if self.context:
            return self.context

        # Use Playwright bundled Chromium for speed
        # (no Chrome profiles/extensions)
        logger.info("Using Playwright's bundled Chromium for optimal performance")

        # Always use simple browser launch with bundled Chromium
        self.browser = self.p.chromium.launch(
            headless=self.headless,
            # Remove executable_path to use bundled Chromium
            args=self._get_optimized_browser_args(),
        )

        # Create fresh context (no saved state for speed)
        self.context = self.browser.new_context()
        self.is_persistent = False

        return self.context

    def close(self):
        if self.context:
            self.context.close()
        if self.browser and not self.is_persistent:
            self.browser.close()

    def is_connected(self) -> bool:
        if self.context:
            return self.context.pages and not self.context.pages[0].is_closed()
        if self.browser:
            return self.browser.is_connected()
        return False

    def add_overlay(
        self,
        page: Page,
        title: str = "",
        subtitle: str = "",
        messages: list[str] = [],
        timeout=8000,
    ):
        """
        Adds a semi-transparent overlay with a custom title, subtitle, message,
        and 'Pause' and 'Stop' buttons to the page. Overlay is invisible until the
        user hovers near the top of the screen.
        """

        overlay_script = """
            // Create the overlay container
            const overlay = document.createElement('div');
            overlay.style.position = 'fixed';
            overlay.style.top = '0';
            overlay.style.left = '0';
            overlay.style.width = '100vw';
            overlay.style.height = '100vh';
            overlay.style.backgroundColor = 'rgba(0, 0, 0, 0.8)';
            overlay.style.color = 'white';
            overlay.style.display = 'flex';
            overlay.style.flexDirection = 'column';
            overlay.style.justifyContent = 'center';
            overlay.style.alignItems = 'center';
            overlay.style.fontSize = '24px';
            overlay.style.zIndex = '9999';
            overlay.style.opacity = '1';
            overlay.style.transition = 'opacity 0.3s ease';
            overlay.style.pointerEvents = 'auto';
            overlay.id = 'custom-overlay';
        """

        if title:
            overlay_script += f"""
                const titleElement = document.createElement('div');
                titleElement.style.fontSize = '32px';
                titleElement.style.fontWeight = 'bold';
                titleElement.style.marginBottom = '10px';
                titleElement.innerText = `{title}`;
                overlay.appendChild(titleElement);
            """
        if subtitle:
            overlay_script += f"""
                const subtitleElement = document.createElement('div');
                subtitleElement.style.fontSize = '24px';
                subtitleElement.style.marginBottom = '10px';
                subtitleElement.innerText = `{subtitle}`;
                overlay.appendChild(subtitleElement);
            """
        if messages:
            for i, message in enumerate(messages):
                overlay_script += f"""
                    const messageElement{i} = document.createElement('div');
                    messageElement{i}.style.fontSize = '20px';
                    messageElement{i}.innerText = `{message}`;
                    overlay.appendChild(messageElement{i});
            """

        overlay_script += """
            // Create hover detection zone
            document.body.appendChild(overlay);
        """

        # add a a timer to display remaining display time and remove the overlay
        overlay_script += f"""
            const timeout = {timeout};
            let remainingSeconds = Math.floor(timeout / 1000);

            // Create timer caption
            const timerCaption = document.createElement('div');
            timerCaption.style.fontSize = '14px';
            timerCaption.style.marginTop = '20px';
            timerCaption.style.opacity = '0.7';
            timerCaption.innerText = `Close in ${{remainingSeconds}} seconds...`;
            overlay.appendChild(timerCaption);

            // Update timer every second
            const countdownInterval = setInterval(() => {{
                remainingSeconds -= 1;
                if (remainingSeconds > 0) {{
                    timerCaption.innerText = (
                        `Close in ${{remainingSeconds}} seconds...`
                    );
                }} else {{
                    clearInterval(countdownInterval);
                }}
            }}, 1000);

            // Remove overlay after timeout
            setTimeout(() => {{
                overlay.remove();
            }}, """
        overlay_script += str(timeout)
        overlay_script += """);
        """

        page.evaluate(overlay_script)
        time.sleep(timeout / 1000)
        return page

    def add_closing_overlay(self, page: Page):
        # say due to human interaction, the bot will close in 5 seconds
        self.add_overlay(page, "Detected Human Interaction", timeout=3000)

    def add_no_interaction_overlay(self, page: Page):
        return self.add_overlay(
            page,
            "💼✨ JobHuntr Bot is Working Its Magic! ✨💼",
            "Sit back and relax — interviews are on the way.",
            [
                "Please avoid interacting with the browser window.",
                (
                    "You can pause ⏸ or stop ⏹ the bot anytime "
                    "from your control panel."
                ),
            ],
        )

    def get_main_page(self, add_human_interaction_overlay: bool = True) -> Page:
        page = None
        if not self.context:
            try:
                self.get_context()
            except Exception as e:
                logger.error(f"Error getting context: {e}")
                return None
        # check if more than one page is open
        if len(self.context.pages) >= 1:
            # close other pages
            for page in self.context.pages[1:]:
                page.close()
            page = self.context.pages[0]
        else:
            page = self.context.new_page()
        if add_human_interaction_overlay:
            self.add_human_interaction_overlay(page)
        return page

    def add_human_interaction_overlay(self, page: Page):
        with open(
            os.path.join(OBJECTS_DIR, "browser_session/overlay.js"),
            "r",
            encoding="utf-8",
        ) as f:
            overlay_script = f.read()
        page.evaluate(overlay_script)

    def scroll_around(self, page: Page):
        # scroll down and back to the top
        # spend 5 seconds in total
        # down and up times are random, but have get back to the top
        logger.info("Scrolling around")
        start_time = time.time()
        height = page.locator("body").bounding_box().get("height")
        scroll_height = random.randint(800, 1200)
        num_scrolls = int(height // scroll_height)

        for _ in range(num_scrolls):
            self.op(
                page.mouse.wheel,
                delta_x=0,
                delta_y=scroll_height,
                ignore_exception=True,
            )
        for _ in range(num_scrolls):
            self.op(
                page.mouse.wheel,
                delta_x=0,
                delta_y=-scroll_height,
                ignore_exception=True,
            )
        end_time = time.time()
        if end_time - start_time < 5:
            time.sleep(5 - (end_time - start_time))

    def take_screenshot(self, page: Page):
        if not page:
            logger.error("No page to take screenshot")
            return None
        screenshot_name = f"screenshot_{time.strftime('%Y%m%d_%H%M%S')}.png"
        screenshot_path = os.path.join(self.screenshot_folder_path, screenshot_name)
        page.screenshot(path=screenshot_path)
        logger.info(f"Screenshot saved to: {screenshot_path}")
        return screenshot_path
