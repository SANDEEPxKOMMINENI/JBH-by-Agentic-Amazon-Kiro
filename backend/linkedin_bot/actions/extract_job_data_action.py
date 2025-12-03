#!/usr/bin/env python3
"""
Extract Job Data Action for LinkedIn Bot

This action extracts job information from LinkedIn job URLs using async Playwright.
Based on the existing PositionInfoExtractor but designed as a standalone action.
Uses async Playwright to work properly with FastAPI.
"""

import logging
import re
from typing import Any, Dict, Optional  # noqa: E402
from urllib.parse import parse_qs, urlparse  # noqa: E402

from activity.base_activity import ActivityType  # noqa: E402
from browser.browser_operator import BrowserOperator  # noqa: E402
from linkedin_bot.position_info_extractor.position_info_extractor import (  # noqa: E402
    PositionInfoExtractor,
)

from .base_action import BaseAction  # noqa: E402

logger = logging.getLogger(__name__)


class ExtractJobDataAction(BaseAction):
    """
    Action to extract job data from LinkedIn job URLs.  # noqa: E402

    This action navigates to a LinkedIn job URL and extracts comprehensive
    job information including title, company, location, description, etc.
    Uses async Playwright to work properly with FastAPI.
    """

    def __init__(self, bot_instance):
        """Initialize the extract job data action"""
        super().__init__(bot_instance)
        self.job_id: Optional[str] = None
        self.browser_operator: Optional[BrowserOperator] = None
        self.page = None

    def send_activity_message(
        self, message: str, activity_type: str = ActivityType.ACTION
    ):
        """Send activity message - simplified for non-websocket environment"""
        # Just log the message since this repo doesn't use websockets
        if activity_type == ActivityType.ACTION:
            self.logger.info(f"{message}")
        elif activity_type == ActivityType.THINKING:
            self.logger.info(f"🤔 {message}")
        elif activity_type == ActivityType.RESULT:
            self.logger.info(f"{message}")
        else:
            self.logger.info(message)

    @property
    def action_name(self) -> str:
        """Return the name of this action"""
        return "extract_job_data"

    def execute(self, job_url: str) -> Dict[str, Any]:
        """
        Execute job data extraction from LinkedIn URL.  # noqa: E402

        Args:
            job_url: LinkedIn job URL
                 (e.g., https://www.linkedin.com/jobs/search/?currentJobId=1234567890)

        Returns:
            Dict containing success status and job data
        """
        try:
            self.send_activity_message(
                f"Starting job data extraction from URL: {job_url}",  # noqa: E402
                ActivityType.ACTION,
            )

            # Validate URL
            if not self._is_valid_linkedin_url(job_url):
                error_msg = (
                    "Invalid LinkedIn job URL. "
                    "Must be https://www.linkedin.com/jobs/search/..."
                )
                self.send_activity_message(f"{error_msg}", ActivityType.RESULT)
                return {"success": False, "error": error_msg, "job_data": None}

            # Extract job ID from URL
            self.job_id = self._extract_job_id(job_url)
            if not self.job_id:
                error_msg = "Could not extract job ID from URL"  # noqa: E402
                self.send_activity_message(f"{error_msg}", ActivityType.RESULT)
                return {"success": False, "error": error_msg, "job_data": None}

            self.send_activity_message(
                f"📋 Extracted job ID: {self.job_id}", ActivityType.THINKING
            )

            # Extract job data using BrowserOperator (same as StartHuntingAction)
            job_data = self._extract_job_data_with_browser_operator(job_url)

            job_title = job_data.get("job_title", "Unknown")
            company = job_data.get("company_name", "Unknown")
            self.send_activity_message(
                f"Successfully extracted job data for: {job_title} at {company}",
                ActivityType.RESULT,
            )

            return {
                "success": True,
                "job_data": job_data,
                "message": "Job data extracted successfully",
            }

        except Exception as e:
            error_msg = f"Error extracting job data from {job_url}: {e}"  # noqa: E402
            self.logger.error(error_msg)
            self.send_activity_message(f"{error_msg}", ActivityType.RESULT)
            return {"success": False, "error": error_msg, "job_data": None}
        finally:
            # Clean up browser resources
            if self.browser_operator:
                try:
                    self.browser_operator.close()
                except Exception as e:
                    self.logger.warning(f"Error closing browser: {e}")
                self.page = None

    def _is_valid_linkedin_url(self, url: str) -> bool:
        """Validate that the URL is a LinkedIn job URL."""
        try:
            parsed = urlparse(url)
            return parsed.hostname == "www.linkedin.com" and parsed.path.startswith(
                "/jobs/search"
            )
        except Exception:
            return False

    def _extract_job_id(self, url: str) -> Optional[str]:
        """Extract job ID from LinkedIn URL."""  # noqa: E402
        try:
            parsed = urlparse(url)
            query_params = parse_qs(parsed.query)

            # Try to get currentJobId from query parameters
            if "currentJobId" in query_params:
                return query_params["currentJobId"][0]

            # Alternative: extract from path if it's a direct job view URL
            if "/jobs/view/" in url:
                match = re.search(r"/jobs/view/(\d+)", url)
                if match:
                    return match.group(1)

            return None
        except Exception as e:
            self.logger.error(
                f"Error extracting job ID from URL {url}: {e}"
            )  # noqa: E402
            return None

    def _extract_job_data_with_browser_operator(self, url: str) -> Dict[str, str]:
        """
        Extract job data using BrowserOperator
        (same pattern as StartHuntingAction).
        """
        try:
            # Launch browser using BrowserOperator (like StartHuntingAction)
            self.send_activity_message(
                "Launching browser for job data extraction...", ActivityType.THINKING
            )

            # Initialize browser operator with visible browser (headless=False)
            self.browser_operator = BrowserOperator(
                headless=False,  # Show browser like main LinkedIn bot
            )

            # Set bot instance reference for stop signal detection
            self.browser_operator.set_bot_instance(self.bot)

            # Start browser and get page
            self.page = self.browser_operator.start()

            # Navigate to the job page
            job_view_url = f"https://www.linkedin.com/jobs/view/{self.job_id}"
            self.send_activity_message(
                f"Navigating to job page: {job_view_url}", ActivityType.THINKING
            )

            # Use browser operator's navigate method
            self.browser_operator.navigate_to(job_view_url)

            # Wait for job details to load
            self.page.wait_for_selector(
                "div.job-details-jobs-unified-top-card__job-title", timeout=10000
            )

            self.send_activity_message(
                "Extracting job information...", ActivityType.THINKING
            )

            # Use the proven PositionInfoExtractor (same as v1 and StartHuntingAction)
            position_info_extractor = PositionInfoExtractor(self.page)
            full_job_data = position_info_extractor.get_position_info()

            # Map to frontend-expected format
            job_data = {
                "job_id": self.job_id,
                "job_title": full_job_data.get("job_title", "")
                or position_info_extractor.get_pos_title(),
                "company_name": full_job_data.get("company_name", ""),
                "location": full_job_data.get("location", ""),
                "post_time": full_job_data.get("post_time", ""),
                "job_description": full_job_data.get(
                    "pos_context", ""
                ),  # Map pos_context to job_description
                "application_url": full_job_data.get("application_url", ""),
                # Include all original data for completeness
                **full_job_data,
            }

            self.logger.info(
                f"Successfully extracted job data for job ID: {self.job_id}"
            )
            return job_data

        except Exception as e:
            raise e
