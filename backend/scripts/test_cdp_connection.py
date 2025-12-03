#!/usr/bin/env python3
"""
Test script to verify CDP connection with the JobHuntr Chrome profile
"""

import logging
import os
import sys
import time

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from browser.browser_operator import BrowserOperator  # noqa: E402
from browser.profile_utils import (  # noqa: E402
    get_jobhuntr_profile_name,
    get_jobhuntr_profile_path,
)

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def test_cdp_connection():
    """Test CDP connection with the JobHuntr Chrome profile"""
    logger.info("=" * 60)
    logger.info("Testing CDP Connection with JobHuntr Chrome profile")
    logger.info("=" * 60)

    # Check if profile exists
    profile_path = get_jobhuntr_profile_path()
    profile_name = get_jobhuntr_profile_name()
    if not os.path.exists(profile_path):
        logger.error(f"Profile not found at: {profile_path}")
        logger.error(
            "Please ensure you've logged into JobHuntr so the Chrome profile can be provisioned."
        )
        return False

    logger.info(f"Profile found at: {profile_path}")

    # Set environment to force CDP mode
    os.environ["JOBHUNTR_BROWSER_MODE"] = "cdp"
    os.environ["JOBHUNTR_CDP_PORT"] = "9222"

    browser = None
    try:
        # Initialize browser operator
        logger.info("Initializing BrowserOperator in CDP mode...")
        browser = BrowserOperator(headless=False)

        # Start browser
        logger.info("Starting browser with CDP connection...")
        page = browser.start()

        logger.info("Browser started successfully!")
        logger.info(f"Browser mode: {'CDP' if browser.use_cdp else 'Bundled'}")
        logger.info(f"CDP port: {browser.cdp_port}")
        logger.info(f"Chrome started by us: {browser.chrome_started_by_us}")

        # Navigate to a test page
        logger.info("Navigating to test page...")
        browser.navigate_to("https://www.example.com")

        logger.info(f"Current URL: {browser.get_current_url()}")
        logger.info(f"Page title: {browser.get_page_title()}")

        # Take a screenshot
        screenshot_path = browser.take_screenshot()
        logger.info(f"Screenshot saved to: {screenshot_path}")

        # Wait a bit to see the browser
        logger.info("Waiting 5 seconds...")
        time.sleep(5)

        logger.info("=" * 60)
        logger.info("CDP Connection Test PASSED!")
        logger.info("=" * 60)
        return True

    except Exception as e:
        logger.error(
            f"CDP Connection Test FAILED for {profile_name}: {e}", exc_info=True
        )
        return False

    finally:
        if browser:
            logger.info("Closing browser...")
            browser.close()
            logger.info("Browser closed")


def main():
    """Main entry point"""
    try:
        success = test_cdp_connection()
        return 0 if success else 1
    except Exception as e:
        logger.error(f"Test failed with error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
