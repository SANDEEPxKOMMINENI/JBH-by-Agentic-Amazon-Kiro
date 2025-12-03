#!/usr/bin/env python3
"""
Start Searching Action for ZipRecruiter Bot

TODO: Manually implement ZipRecruiter-specific CSS selectors and logic:
1. Navigate to ZipRecruiter and handle login (if required)
2. Fill in search form with job title and location
3. Apply platform-specific filters
4. Extract job listings using ZipRecruiter CSS selectors
5. Process jobs with ATS analysis and queueing
"""

import logging
import os
import random
import re
import sys
import time
import traceback
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from urllib.parse import urljoin

import requests

# Add parent directories to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from browser.browser_operator import BrowserOperator
from constants import SERVICE_GATEWAY_URL
from indeed_bot.actions.start_searching_action.start_searching_action import (
    StartSearchingAction as IndeedStartSearchingAction,
)
from shared.models.application_history import ApplicationStatus
from util.application_history_id_generator import (
    generate_application_history_id,
    generate_job_description_id,
)
from ziprecruiter_bot.actions.base_action import BaseAction

logger = logging.getLogger(__name__)


class StartSearchingAction(BaseAction):
    """Action to start the ZipRecruiter job searching and queueing process"""

    def __init__(self, bot_instance):
        super().__init__(bot_instance)
        self.workflow_run_id = bot_instance.workflow_run_id
        self.cur_job_data = {}  # Current job data for maybe_skip_application
        self.date_posted_days = None

        # Will be initialized after browser operator is ready
        self.config_reader = None
        self.application_history_tracker = None

    @property
    def action_name(self) -> str:
        return "start_searching"

    def _clean_job_title(self, job_title: str) -> str:
        """Remove unwanted suffixes from job titles"""
        if not job_title:
            return job_title
        # TODO: Add ZipRecruiter-specific cleaning if needed
        return job_title.strip()

    def execute(self) -> Dict[str, Any]:
        """
        Start the ZipRecruiter searching process
        Returns status dict with success/error info
        """
        try:
            self.logger.info(f"Starting ZipRecruiter bot {self.bot.bot_id}")

            if self.bot.is_running:
                return {
                    "success": False,
                    "message": "Bot is already running",
                    "status": "already_running",
                }

            # Mark as running BEFORE using browser_operator methods
            self.bot.is_running = True
            self.bot.status = "running"

            # Initialize browser
            self._init_browser_sync()

            self.send_activity_message("Browser launched successfully")

            # Initialize config reader and application history tracker FIRST
            self._init_trackers()

            # Navigate to ZipRecruiter homepage
            # TODO: Update URL if needed
            self.bot.current_url = self._navigate_to_ziprecruiter_sync()
            self.send_activity_message("Opened ZipRecruiter homepage")

            login_success, login_error = self._check_and_handle_login()
            if not login_success:
                return {
                    "success": False,
                    "message": f"Failed to login: {login_error}",
                    "status": "error",
                }

            # Generate search URL with AI and navigate to it
            time.sleep(5)
            built_url = self._build_ziprecruiter_url_from_db_config()
            if built_url:
                self.send_activity_message(
                    f"Opening ZipRecruiter search page: `{built_url}`"
                )
                self.bot.current_url = self.bot.browser_operator.navigate_to(built_url)
                time.sleep(3)  # Wait for search results to load
            else:
                self.logger.error("Failed to build ZipRecruiter URL from config")
                return {
                    "success": False,
                    "message": "Failed to build ZipRecruiter URL from config",
                    "status": "error",
                }

            self.send_status_update(
                "running", "Successfully launched and navigated to ZipRecruiter"
            )

            # Perform job searching steps
            time.sleep(5)
            self._perform_job_searching_steps()

            # After completing the search, automatically stop the bot
            self.logger.info(
                f"ZipRecruiter bot {self.bot.bot_id} completed job searching batch"
            )

            # Send completion message
            self.send_activity_message(
                "Job searching batch completed successfully! Ready to start a new batch."
            )

            # Mark as not running and update status
            self.bot.is_running = False
            self.bot.status = "completed"

            # Send final status update
            self.send_status_update(
                "completed", "Job searching batch completed successfully"
            )

            return {
                "success": True,
                "message": "ZipRecruiter bot completed job searching batch successfully",
                "status": "completed",
                "current_url": self.bot.current_url,
            }

        except Exception as e:
            self.logger.error(f"Failed to start ZipRecruiter bot in execute: {e}")

            traceback.print_exc()

            # Cleanup on error
            self._cleanup_on_error()

            self.send_status_update("error", f"Failed to start: {str(e)}")

            return {
                "success": False,
                "message": f"Failed to start ZipRecruiter bot in execute: {str(e)}",
                "status": "error",
            }

    def _init_browser_sync(self):
        """Initialize browser with bundled Chromium (sync version)"""
        try:
            self.logger.info("Initializing browser operator")

            # Fetch headless_on setting from workflow run config
            headless_on = False
            try:
                from services.supabase_client import supabase_client

                workflow_run = supabase_client.get_workflow_run(self.workflow_run_id)
                if workflow_run:
                    headless_on = getattr(workflow_run, "headless_on", False) or False
                    self.logger.info(f"Using headless mode: {headless_on}")
            except Exception as e:
                self.logger.warning(f"Failed to fetch headless_on setting: {e}")

            # Create browser operator with state file
            self.bot.browser_operator = BrowserOperator(
                headless=headless_on,
            )

            # Set bot instance reference for stop signal detection
            self.bot.browser_operator.set_bot_instance(self.bot)

            # Start browser (creates and returns page)
            self.bot.page = self.bot.browser_operator.start()

            self.logger.info("Browser operator initialized successfully")

        except Exception as e:
            self.logger.error(f"Failed to initialize browser: {e}")
            raise

    def _init_trackers(self):
        """Initialize config reader and application history tracker"""
        try:
            # Initialize config reader from database
            from shared.config_reader import ConfigReader

            self.config_reader = ConfigReader(
                user_id=self.bot.user_id, workflow_run_id=self.workflow_run_id
            )
            self.config_reader.load_configuration()

            # Initialize application history tracker
            from shared.application_history_tracker import ApplicationHistoryTracker

            self.application_history_tracker = ApplicationHistoryTracker(
                self.bot.user_id
            )

            self.logger.info("Trackers initialized successfully")

        except Exception as e:
            self.logger.error(f"Failed to initialize trackers: {e}")
            raise

    def _navigate_to_ziprecruiter_sync(self) -> str:
        """Navigate to ZipRecruiter homepage"""
        try:
            # TODO: Update URL to ZipRecruiter's actual job search page
            url = "https://www.ziprecruiter.com/jobs-search"
            current_url = self.bot.browser_operator.navigate_to(url)
            time.sleep(2)  # Wait for page to stabilize
            return current_url
        except Exception as e:
            self.logger.error(f"Failed to navigate to ZipRecruiter: {e}")
            raise

    def _build_ziprecruiter_url_from_db_config(self) -> Optional[str]:
        """Build ZipRecruiter search URL from workflow run config in database"""
        if not self.config_reader:
            self.logger.info(
                "ConfigReader not initialized, cannot build ZipRecruiter URL"
            )
            return None

        bot_config = self.config_reader.workflow_run_config
        if not bot_config:
            self.logger.info("No workflow run config in database, cannot build URL")
            return None

        try:
            from services.jwt_token_manager import jwt_token_manager

            token = jwt_token_manager.get_token()
            headers = {"Content-Type": "application/json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"

            response = requests.post(
                f"{SERVICE_GATEWAY_URL}/api/infinite-runs/generate-platform-url",
                json={"platform": "ziprecruiter", "bot_config": bot_config},
                headers=headers,
                timeout=10,
            )

            if response.status_code == 200:
                result = response.json()
                if result.get("success") and result.get("url"):
                    built_url = result["url"]
                    self.logger.info(
                        f"Successfully built ZipRecruiter URL: {built_url}"
                    )
                    return built_url
                else:
                    error_msg = result.get("error", "Unknown error")
                    self.logger.error(f"Failed to build ZipRecruiter URL: {error_msg}")
                    return None
            else:
                self.logger.error(
                    f"Service-gateway returned error "
                    f"{response.status_code}: {response.text}"
                )
                return None

        except Exception as e:
            self.logger.error(f"Exception while building ZipRecruiter URL: {e}")
            return None

    def _fill_search_form(self):
        """Fill in the ZipRecruiter search form with config-driven values."""
        try:
            self.send_activity_message("Filling in search criteria...")

            job_title = self.config_reader.filters.job_description or ""
            location = (
                self.config_reader.filters.location
                or self.config_reader.workflow_run_config.get(
                    "location_preferences", ""
                )
            )

            if not job_title:
                self.logger.warning(
                    f"Missing search criteria - job_title: '{job_title}'"
                )
                self.send_activity_message(
                    "Warning: Missing job title or location in config"
                )
                return

            search_bar = self.bot.page.locator("div#search-bar")

            combined_input = search_bar.locator(
                "input[placeholder*='Search job title and location']"
            )
            if combined_input.count() > 0 and combined_input.first.is_visible():
                self.bot.browser_operator.click_with_op(combined_input.first)
                time.sleep(0.5)

            job_title_input = search_bar.locator(
                "input[placeholder*='Search job title']"
            )
            if job_title_input.count() > 0 and job_title_input.first.is_visible():
                self.bot.browser_operator.fill_with_op(job_title_input.first, job_title)
                self.send_activity_message(f"Job title set to: {job_title}")
            else:
                self.logger.warning("Job title input not found or not visible")

            location_input = search_bar.locator(
                "input[placeholder*='Search location or remote']"
            )
            if location_input.count() > 0 and location_input.first.is_visible():
                self.bot.browser_operator.fill_with_op(location_input.first, location)
                self.send_activity_message(f"Location set to: {location}")
            else:
                self.logger.warning("Location input not found or not visible")

            search_button = search_bar.locator("button[type*=submit]")
            if search_button.count() > 0 and search_button.first.is_visible():
                self.bot.browser_operator.click_with_op(search_button.first)
                self.send_activity_message("Submitted ZipRecruiter search")
            else:
                self.logger.warning("Search button not found or not visible")
                self.send_activity_message(
                    "Warning: Could not find ZipRecruiter search button"
                )

        except Exception as e:
            self.logger.error(f"Failed to fill search form: {e}")
            self.send_activity_message(f"Error filling search form: {str(e)}")

    def _perform_job_searching_steps(self):
        """
        Main job searching loop - iterate current result pane, extract job info,
        and queue listings for the workflow.
        """
        try:
            self.send_activity_message("Starting job search and queue process...")

            page_number = 1
            total_processed = 0
            total_queued = 0

            while True:
                if not self.bot.is_running:
                    self.logger.info("Stop signal detected, halting job processing")
                    break

                results_container_locator = self.bot.page.locator(
                    "section[class*=job_results_two_pane]"
                )
                time.sleep(5)
                if results_container_locator.count() == 0:
                    self.logger.warning("Job results section not found")
                    self.send_activity_message("No job results found")
                    break

                results_container = results_container_locator.first
                job_cards_locator = results_container.locator(
                    "div[class*=job_result_two_pane_v2]"
                )

                if job_cards_locator.count() == 0:
                    self.logger.warning("No job cards found in results container")
                    self.send_activity_message("No job listings found on this page")
                    break

                first_card = job_cards_locator.first
                if first_card.count() > 0 and first_card.is_visible():
                    self.bot.browser_operator.click_with_op(first_card)
                    time.sleep(1)
                else:
                    self.logger.warning(
                        "First job card not visible, attempting to proceed"
                    )

                self._scroll_results_area(results_container)

                job_cards_locator = results_container.locator(
                    "div[class*=job_result_two_pane_v2]"
                )
                total_count = job_cards_locator.count()

                self.logger.info(f"Processing {total_count} job cards")
                self.send_activity_message(
                    f"Loaded {total_count} job listings, processing..."
                )

                page_processed_count = 0
                page_queued_count = 0

                for index in range(total_count):
                    if not self.bot.is_running:
                        self.logger.info(
                            "Stop signal detected while processing job cards"
                        )
                        break

                    try:
                        job_cards_locator = results_container.locator(
                            "div[class*=job_result_two_pane_v2]"
                        )
                        current_count = job_cards_locator.count()

                        if current_count <= index:
                            self.logger.debug(
                                f"Only {current_count} job cards available, skipping index {index}"
                            )
                            self._scroll_results_area(results_container)
                            job_cards_locator = results_container.locator(
                                "div[class*=job_result_two_pane_v2]"
                            )
                            current_count = job_cards_locator.count()
                            if current_count <= index:
                                self.logger.warning(
                                    f"Job card {index + 1} still unavailable after rescroll, skipping"
                                )
                                continue

                        job_card = job_cards_locator.nth(index).locator("button").last
                        if job_card.count() == 0:
                            self.logger.warning(
                                f"Job card locator for index {index + 1} not found, skipping"
                            )
                            continue

                        if not job_card.is_visible():
                            try:
                                self.bot.browser_operator.scroll_into_view_with_op(
                                    job_card, sleep_after=0.2
                                )
                            except Exception as scroll_error:
                                self.logger.debug(
                                    f"Failed to scroll job card {index + 1} into view: {scroll_error}"
                                )

                        self.logger.info(f"Processing job {index + 1}/{total_count}")
                        self.bot.browser_operator.click_with_op(job_card)
                        time.sleep(0.6)

                        job_data = self._extract_job_details(job_card)

                        if not job_data.get("job_title") or not job_data.get(
                            "company_name"
                        ):
                            self.logger.warning(
                                f"Job {index + 1}: missing title or company, skipping"
                            )
                            continue

                        self.cur_job_data = job_data
                        page_processed_count += 1

                        try:
                            queued = self._queue_job_for_review(job_data)
                        except Exception as queue_error:
                            queued = False
                            self.logger.error(
                                f"Queueing job {index + 1} failed: {queue_error}"
                            )

                        if queued:
                            page_queued_count += 1

                        time.sleep(0.3)

                    except Exception as job_error:
                        self.logger.error(
                            f"Error processing job {index + 1}/{total_count}: {job_error}"
                        )
                        continue

                total_processed += page_processed_count
                total_queued += page_queued_count

                self.logger.info(
                    f"Page {page_number} completed - processed {page_processed_count}, queued {page_queued_count}"
                )
                self.send_activity_message(
                    f"Page {page_number} completed: {page_processed_count} jobs processed, {page_queued_count} jobs queued"
                )

                if not self._navigate_to_next_page():
                    break

                page_number += 1
                time.sleep(2)

            self.logger.info(
                f"Search completed - Total pages: {page_number}, Total processed: {total_processed}, Total queued: {total_queued}"
            )
            self.send_activity_message(
                f"Search completed: {page_number} pages processed, {total_processed} jobs evaluated, {total_queued} jobs queued"
            )

        except Exception as e:
            self.logger.error(f"Error during job searching steps: {e}")
            raise

    def _scroll_results_area(self, scroll_container):
        """Scroll the results pane to load additional listings."""
        try:
            scroll_height = scroll_container.evaluate("el => el.scrollHeight")
            if not scroll_height:
                return

            steps = max(3, int(scroll_height // 600) + 1)
            for _ in range(steps):
                scroll_container.evaluate(
                    "(el, amount) => el.scrollBy(0, amount)", scroll_height / steps
                )
                time.sleep(random.uniform(0.2, 0.4))
        except Exception as e:
            self.logger.warning(f"Failed to scroll results area: {e}")

    def _navigate_to_next_page(self) -> bool:
        """Navigate to next result page if available."""
        try:
            # Use a shorter timeout for checking next button to avoid long waits
            next_button = self.bot.page.locator("button[title*='Next Page']")

            # Check count with explicit short timeout to prevent hanging
            try:
                button_count = next_button.count()
            except Exception as count_error:
                self.logger.warning(f"Error checking next button count: {count_error}")
                return False

            if button_count == 0:
                self.logger.info("No next page button found")
                return False

            button = next_button.first
            if not button.is_enabled() or not button.is_visible():
                self.logger.info("Next page button is not clickable")
                return False

            if not self.bot.is_running:
                self.logger.info("Stop signal detected before navigating to next page")
                return False

            self.send_activity_message("Moving to next page...")
            self.bot.browser_operator.click_with_op(button)
            self.logger.info("Navigated to next page")
            return True
        except Exception as e:
            self.logger.error(f"Failed to navigate to next page: {e}")
            return False

    def _extract_job_details(self, job_card) -> dict:
        """Extract structured details from the currently selected job."""
        detail_container = self.bot.page.locator(
            "div[data-testid*='job-details-scroll-container']"
        )
        if detail_container.count() == 0:
            self.logger.warning("Job detail container not found")
            return {}

        try:
            job_title, title_parent = self._get_detail_title(detail_container)
            company_name = self._get_detail_company(title_parent)
            location = self._get_detail_location(title_parent)

            paragraph_texts = detail_container.locator("p").all_inner_texts()
            job_type_text = self._get_detail_job_type(detail_container, paragraph_texts)
            salary_text = self._get_detail_salary_text(paragraph_texts)
            posted_text = self._get_detail_posted_text(paragraph_texts)

            salary_range = self._parse_salary_range(salary_text)
            post_time = self._parse_posted_time(posted_text)
            pos_context = self._get_detail_pos_context(detail_container)
            application_url = self._extract_application_url(detail_container, job_card)

            return {
                "job_title": job_title,
                "company_name": company_name,
                "location": location,
                "job_type": job_type_text.strip() if job_type_text else "",
                "salary_range": salary_range,
                "post_time": post_time,
                "pos_context": pos_context,
                "application_url": application_url,
            }
        except Exception as e:
            self.logger.error(f"Failed to extract job details: {e}")
            return {}

    def _extract_application_url(self, detail_container, job_card) -> str:
        """Determine the best application URL for the current job."""
        try:
            apply_link = detail_container.locator("a[aria-label*='Apply']")
            if apply_link.count() > 0:
                href = apply_link.first.get_attribute("href")
                if href:
                    return urljoin(self.bot.page.url, href)

        except Exception as e:
            self.logger.warning(f"Unable to determine application URL: {e}")

        # Fallback to current URL if no apply link found
        return self.bot.page.url

    def _get_detail_title(self, detail_container) -> tuple[str, Optional[Any]]:
        """Extract job title and return its parent container for chained lookups."""
        try:
            title_locator = detail_container.locator(
                "h2[class*='md:text-header-md-tablet']"
            )
            if title_locator.count() > 0:
                node = title_locator.first
                return node.inner_text().strip(), node.locator("..")
        except Exception as e:
            self.logger.warning(f"Failed to extract job title: {e}")
        return "", None

    def _get_detail_company(self, title_parent: Optional[Any]) -> str:
        """Extract company name from the title section."""
        if not title_parent:
            return ""
        try:
            company_locator = title_parent.locator("a")
            if company_locator.count() > 0:
                return company_locator.first.inner_text().strip()
        except Exception as e:
            self.logger.warning(f"Failed to extract company name: {e}")
        return ""

    def _get_detail_location(self, title_parent: Optional[Any]) -> str:
        """Extract location text from the title section."""
        if not title_parent:
            return ""
        try:
            location_locator = title_parent.locator("p")
            if location_locator.count() > 0:
                location_text = location_locator.first.inner_text().strip()
                return location_text.split("•")[0].strip()
        except Exception as e:
            self.logger.warning(f"Failed to extract location: {e}")
        return ""

    def _get_detail_job_type(
        self, detail_container, paragraph_texts: list[str]
    ) -> Optional[str]:
        """Extract job type string from detail container or paragraph text."""
        try:
            job_type_locator = detail_container.locator(
                "p:text-matches('Full-time|Part-time|Contract|Internship|Temporary|Per diem|Other')"
            )
            if job_type_locator.count() > 0:
                return job_type_locator.first.inner_text().strip()

            job_type_rx = re.compile(
                r"(Full-time|Part-time|Contract|Internship|Temporary|Per diem|Other|Freelance)",
                re.I,
            )
            return next(
                (text for text in paragraph_texts if job_type_rx.search(text)), None
            )
        except Exception as e:
            self.logger.warning(f"Failed to extract job type: {e}")
            return None

    def _get_detail_salary_text(self, paragraph_texts: list[str]) -> Optional[str]:
        """Pull the first paragraph that looks like a salary string."""
        salary_rx = re.compile(
            r"\$\s?\d+(?:[.,]\d+)?(?:[KkMm])?(?:\s*-\s*\$?\d+(?:[.,]\d+)?(?:[KkMm])?)?\s*/\s*(?:hr|hour|yr|year|month|week)s?",
            re.I,
        )
        return next((text for text in paragraph_texts if salary_rx.search(text)), None)

    def _get_detail_posted_text(self, paragraph_texts: list[str]) -> Optional[str]:
        """Pull the paragraph that contains posted timing information."""
        posted_rx = re.compile(r"Posted.*", re.I)
        return next((text for text in paragraph_texts if posted_rx.search(text)), None)

    def _get_detail_pos_context(self, detail_container) -> str:
        """Collect job description context text."""
        try:
            description_heading = detail_container.locator(
                "h2", has_text=re.compile("Job description", re.I)
            )
            if description_heading.count() > 0:
                description_container = description_heading.first.locator("..")
                paragraph_locator = description_container.locator("p")
                if paragraph_locator.count() > 0:
                    texts = [
                        text.strip()
                        for text in paragraph_locator.all_inner_texts()
                        if text.strip()
                    ]
                    if texts:
                        return "\n".join(texts)
        except Exception as e:
            self.logger.warning(f"Failed to extract job description: {e}")

        try:
            return detail_container.inner_text().strip()
        except Exception:
            return ""

    def _parse_salary_range(self, salary_text: Optional[str]) -> list[int]:
        """Convert salary text into a numeric [min, max] list."""
        if not salary_text:
            return []

        try:
            parts = re.findall(r"\$?\s*([\d.,]+)\s*([KkMm]?)", salary_text)
            if not parts:
                return []

            unit = "year"
            lowered = salary_text.lower()
            if "/hr" in lowered or "/hour" in lowered:
                unit = "hour"
            elif "/week" in lowered:
                unit = "week"
            elif "/month" in lowered:
                unit = "month"
            elif "/day" in lowered:
                unit = "day"

            salaries = []
            for value, suffix in parts:
                numeric = float(value.replace(",", ""))
                normalized = self._normalize_salary_amount(numeric, suffix)
                annualized = self._convert_salary_to_annual(normalized, unit)
                salaries.append(annualized)

            if not salaries:
                return []

            if len(salaries) == 1:
                salaries = salaries * 2

            salaries = sorted(int(round(amount)) for amount in salaries[:2])
            return salaries
        except Exception as e:
            self.logger.warning(f"Failed to parse salary range '{salary_text}': {e}")
            return []

    def _normalize_salary_amount(self, value: float, suffix: str) -> float:
        """Scale salary numbers based on shorthand suffixes."""
        suffix = suffix.lower()
        if suffix == "k":
            return value * 1_000
        if suffix == "m":
            return value * 1_000_000
        return value

    def _convert_salary_to_annual(self, amount: float, unit: str) -> float:
        """Annualize salary amount based on the provided unit."""
        unit = unit.lower()
        if unit == "hour":
            return amount * 2080
        if unit == "week":
            return amount * 52
        if unit == "month":
            return amount * 12
        if unit == "day":
            return amount * 260
        return amount

    def _parse_posted_time(self, posted_text: Optional[str]) -> str:
        """Translate posted text like 'Posted 19 days ago' into an ISO timestamp."""
        if not posted_text:
            return ""

        try:
            now = datetime.utcnow()
            lowered = posted_text.lower()

            if "just" in lowered or "today" in lowered:
                return now.replace(microsecond=0).isoformat() + "Z"

            match = re.search(
                r"posted\s+(\d+)\+?\s*(minute|hour|day|week|month|year)s?", lowered
            )
            if match:
                value = int(match.group(1))
                unit = match.group(2)
                delta_map = {
                    "minute": timedelta(minutes=value),
                    "hour": timedelta(hours=value),
                    "day": timedelta(days=value),
                    "week": timedelta(weeks=value),
                    "month": timedelta(days=value * 30),
                    "year": timedelta(days=value * 365),
                }
                timestamp = now - delta_map.get(unit, timedelta(0))
            else:
                timestamp = now

            return timestamp.replace(microsecond=0).isoformat() + "Z"
        except Exception as e:
            self.logger.warning(f"Failed to parse posted time '{posted_text}': {e}")
            return ""

    def _queue_job_for_review(self, job_data: dict) -> bool:
        """
        Queue individual job with all checks using shared utilities.
        Mirrors the Indeed bot flow: dedupe, create application history, run interest
        and ATS analysis, optionally generate optimized resume, then queue.
        """
        try:
            application_url = job_data.get("application_url", "")
            if not application_url:
                self.logger.info("No application URL, skipping job")
                return False

            job_desc_id = generate_job_description_id(application_url=application_url)
            app_history_id = generate_application_history_id(
                application_url=application_url, user_id=self.bot.user_id
            )

            existing_job = self.application_history_tracker.get_job_item_from_history(
                app_history_id
            )
            if existing_job:
                company = job_data.get("company_name", "Unknown Company")
                title = self._clean_job_title(
                    job_data.get("job_title", "Unknown Position")
                )
                existing_status = existing_job.get("status", "unknown")

                # Note: Despite the confusing name, jobs IN this set will be SKIPPED
                reprocessable_statuses = [
                    ApplicationStatus.QUEUED.value,
                    ApplicationStatus.REMOVED.value,
                    ApplicationStatus.SUBMITTING.value,
                    ApplicationStatus.APPLIED.value,
                ]

                # Add SKIPPED to skip list if skip_previously_skipped_jobs is enabled
                if self.config_reader.filters.skip_previously_skipped_jobs:
                    reprocessable_statuses.append(ApplicationStatus.SKIPPED.value)

                reprocessable_statuses = set(reprocessable_statuses)

                if existing_status in reprocessable_statuses:
                    self.activity_manager.start_application_thread(
                        company, title, existing_status
                    )
                    msg = (
                        f"Skipping {company} | {title} "
                        f"(already processed with status: {existing_status})"
                    )
                    self.send_activity_message(msg)
                    self.logger.info(
                        "Skipping job %s - %s - already exists in database with status: %s",
                        company,
                        title,
                        existing_status,
                    )
                    return False
                else:
                    msg = (
                        f"Reprocessing {company} | {title} "
                        f"(previous status: {existing_status})"
                    )
                    self.send_activity_message(msg)
                    self.logger.info(
                        "Reprocessing job %s - %s - previous status was: %s",
                        company,
                        title,
                        existing_status,
                    )

            post_time = job_data.get("post_time")
            if not post_time:
                post_time = datetime.utcnow().replace(microsecond=0).isoformat()
                job_data["post_time"] = post_time
            else:
                post_time = str(post_time)

            self.cur_job_data = job_data

            position_data = {
                "job_description_id": job_desc_id,
                "application_url": application_url,
                "company_name": job_data.get("company_name", ""),
                "location": job_data.get("location", ""),
                "job_title": job_data.get("job_title", ""),
                "pos_context": job_data.get("pos_context", ""),
                "job_type": job_data.get("job_type", ""),
                "salary_range": job_data.get("salary_range", ""),
                "post_time": post_time,
                "num_applicants": job_data.get("num_applicants", 0),
                "workflow_run_id": self.workflow_run_id,
                "status": ApplicationStatus.STARTED.value,
                "resume_id": (
                    self.config_reader.profile.resume_id if self.config_reader else None
                ),
            }

            for attr_name, attr_value in position_data.items():
                self.application_history_tracker.update_application(
                    app_history_id, attr_name, attr_value
                )

            self.application_history_tracker.cur_recording_app_history_id = (
                app_history_id
            )

            self.logger.debug("Updated application history for job: %s", app_history_id)

            try:
                self.application_history_tracker.create_application_history()
            except Exception as create_error:
                from exceptions import DailyLimitException, SubscriptionLimitException

                if isinstance(
                    create_error, (SubscriptionLimitException, DailyLimitException)
                ):
                    raise
                self.logger.error(
                    "Failed to create application history: %s", create_error
                )
                raise

            self.logger.info(
                "Created application history and job description for: %s at %s",
                job_data.get("job_title"),
                job_data.get("company_name"),
            )

            should_skip = self.maybe_skip_application()
            if should_skip:
                self.logger.info(
                    "Skipping application to %s - %s",
                    job_data.get("company_name"),
                    job_data.get("job_title"),
                )
                return False

            self.application_history_tracker.update_application(
                app_history_id, "status", ApplicationStatus.QUEUED.value
            )
            self.application_history_tracker.sync_application_history()

            self.activity_manager.update_application_status(
                ApplicationStatus.QUEUED.value
            )

            company_name = job_data.get("company_name", "Unknown")
            job_title = self._clean_job_title(job_data.get("job_title", "Unknown"))
            self.logger.info(
                "Sending queued message with status: %s, thread: %s",
                self.activity_manager.current_thread_status,
                self.activity_manager.current_thread_title,
            )
            self.send_activity_message(f"Queued: {company_name} | {job_title}")
            return True

        except Exception as e:
            self.logger.error(f"Error queueing job: {e}")
            return False

    def maybe_skip_application(self):
        """Delegate interest/ATS pipeline to the shared Indeed implementation."""
        return IndeedStartSearchingAction.maybe_skip_application(self)

    def maybe_display_activity(self, text: str):
        """Show AI thinking in activity logs (shared implementation)."""
        return IndeedStartSearchingAction.maybe_display_activity(self, text)

    def analyze_ats_score(self, job_data):
        """Run ATS analysis using shared Indeed workflow."""
        return IndeedStartSearchingAction.analyze_ats_score(self, job_data)

    def _get_user_filters_from_supabase(self):
        """Fetch workflow filters via shared implementation."""
        return IndeedStartSearchingAction._get_user_filters_from_supabase(self)

    def _check_if_staffing_company(self) -> bool:
        """Reuse staffing company detection logic from Indeed bot."""
        return IndeedStartSearchingAction._check_if_staffing_company(self)

    def _generate_ats_optimized_resume(self):
        """Generate ATS-optimized resume using shared implementation."""
        return IndeedStartSearchingAction._generate_ats_optimized_resume(self)

    def _upload_pdf_to_blob_storage(self, pdf_path: str, ats_resume_id: str) -> str:
        """Upload optimized resume PDF via shared helper."""
        return IndeedStartSearchingAction._upload_pdf_to_blob_storage(
            self, pdf_path, ats_resume_id
        )

    def _update_ats_resume_blob_url(self, ats_resume_id: str, blob_url: str) -> bool:
        """Update blob URL for ATS resume record via shared helper."""
        return IndeedStartSearchingAction._update_ats_resume_blob_url(
            self, ats_resume_id, blob_url
        )

    def _cleanup_on_error(self):
        """Cleanup on error"""
        try:
            self.bot.is_running = False
            self.bot.status = "error"

            if self.bot.browser_operator:
                try:
                    self.bot.browser_operator.close()
                except Exception as e:
                    self.logger.error(f"Error closing browser during cleanup: {e}")

        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")

    def _check_and_handle_login(self) -> tuple[bool, str]:
        """
        Check if sign-in is required and guide the user through login if needed.
        Returns (success, error_message)
        """
        try:
            if self._is_logged_in():
                self.send_activity_message("Already logged in to ZipRecruiter")
                return True, ""

            # Open account menu to reveal login option
            menu_button = self.bot.page.locator(
                "div[data-testid*='logged-out-dropdown']"
            )
            if menu_button.count() > 0 and menu_button.first.is_visible():
                try:
                    self.bot.browser_operator.click_with_op(menu_button.first)
                    time.sleep(1)
                except Exception as e:
                    self.logger.warning(f"Failed to open account menu: {e}")

            login_link = [
                a
                for a in self.bot.page.locator(
                    "a[href*='/authn/login']", has_text="Log In"
                ).all()
                if a.is_visible()
            ]

            if login_link:
                self.send_activity_message("Sign-in required - opening login page")
                self.bot.browser_operator.click_with_op(login_link[0])
                time.sleep(2)
                return self.login_and_save_state()

            # If login link isn't visible, re-check login status in case auto-login occurred
            if self._is_logged_in():
                self.send_activity_message("Already logged in to ZipRecruiter")
                return True, ""

            return False, "Unable to locate ZipRecruiter login option"

        except Exception as e:
            self.logger.error(f"Error during login check: {e}")
            return False, f"Login check error: {str(e)}"

    def login_and_save_state(self) -> tuple[bool, str]:
        """
        Handle login flow and persist browser storage state.
        Returns (success, error_message)
        """
        try:
            self.send_activity_message("Please complete ZipRecruiter login")
            self.send_activity_message("Waiting for login (timeout: 5 minutes)...")

            login_timeout = 300
            start_time = time.time()

            while time.time() - start_time < login_timeout:
                if not self.bot.is_running:
                    return False, "Bot stopped while waiting for login"

                if self._is_logged_in():
                    self.send_activity_message("Login detected!")
                    return True, ""

                time.sleep(2)

            return False, "Login timeout - please try again"

        except Exception as e:
            self.logger.error(f"Login error: {e}")
            return False, f"Login error: {str(e)}"

    def _is_logged_in(self) -> bool:
        """Determine if the user is already authenticated on ZipRecruiter."""
        try:
            logout_link = self.bot.page.locator(
                "div[role='menu'] a[href*='/logout']", has_text="Log out"
            )
            return logout_link.count() > 0
        except Exception as e:
            self.logger.error(f"Error checking login status: {e}")
            return False
