#!/usr/bin/env python3
"""
Start Searching Action for Glassdoor Bot
"""

import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import requests

# Add parent directories to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from browser.browser_operator import BrowserOperator
from constants import SERVICE_GATEWAY_URL
from glassdoor_bot.actions.base_action import BaseAction
from shared.models.application_history import ApplicationStatus

logger = logging.getLogger(__name__)


class StartSearchingAction(BaseAction):
    """Action to start the Glassdoor job searching and queueing process"""

    def __init__(self, bot_instance):
        super().__init__(bot_instance)
        self.workflow_run_id = bot_instance.workflow_run_id
        self.cur_job_data: dict[str, Any] = {}

        # Will be initialized after browser operator is ready
        self.config_reader = None
        self.application_history_tracker = None

    @property
    def action_name(self) -> str:
        return "start_searching"

    def _clean_job_title(self, job_title: str) -> str:
        """Normalize job titles for activity reporting."""
        if not job_title:
            return job_title
        return job_title.strip()

    def execute(self) -> Dict[str, Any]:
        """
        Start the Glassdoor searching process
        Returns status dict with success/error info
        """
        try:
            self.logger.info(f"Starting Glassdoor bot {self.bot.bot_id}")

            if self.bot.is_running:
                return {
                    "success": False,
                    "message": "Bot is already running",
                    "status": "already_running",
                }

            self.bot.is_running = True
            self.bot.status = "running"

            # Initialize browser
            self._init_browser_sync()

            self.send_activity_message("Browser launched successfully")

            # Initialize config reader and application history tracker
            self._init_trackers()

            # Navigate to Glassdoor homepage
            self.bot.current_url = self._navigate_to_glassdoor_sync()
            self.send_activity_message("Opened Glassdoor homepage")

            # Check if sign-in is required and handle login
            login_success, login_error = self._check_and_handle_login()
            if not login_success:
                return {
                    "success": False,
                    "message": f"Failed to login: {login_error}",
                    "status": "error",
                }

            # Build Glassdoor URL from config and navigate to it
            time.sleep(5)
            built_url = self._build_glassdoor_url_from_db_config()
            if built_url:
                self.send_activity_message(
                    f"Opening Glassdoor search page: `{built_url}`"
                )
                self.bot.current_url = self.bot.browser_operator.navigate_to(built_url)
                time.sleep(3)
            else:
                return {
                    "success": False,
                    "message": "Failed to build Glassdoor URL",
                    "status": "error",
                }

            # Close job alert modal if it appears
            time.sleep(5)
            self._maybe_close_job_alert_modal()

            self.send_status_update(
                "running", "Successfully launched and navigated to Glassdoor"
            )

            # Perform job searching steps
            time.sleep(5)
            self._perform_job_searching_steps()

            # After completing the search, automatically stop the bot
            self.logger.info(
                f"Glassdoor bot {self.bot.bot_id} completed job searching batch"
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
                "message": "Glassdoor bot completed job searching batch successfully",
                "status": "completed",
                "current_url": self.bot.current_url,
            }

        except Exception as e:
            self.logger.error(f"Failed to start Glassdoor bot: {e}")

            import traceback

            traceback.print_exc()

            # Cleanup on error
            self._cleanup_on_error()

            self.send_status_update("error", f"Failed to start: {str(e)}")

            return {
                "success": False,
                "message": f"Failed to start Glassdoor bot: {str(e)}",
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

    def _navigate_to_glassdoor_sync(self) -> str:
        """Navigate to Glassdoor homepage"""
        try:
            url = "https://www.glassdoor.com/Job/jobs.htm"
            current_url = self.bot.browser_operator.navigate_to(url)
            time.sleep(2)  # Wait for page to stabilize
            return current_url
        except Exception as e:
            self.logger.error(f"Failed to navigate to Glassdoor: {e}")
            raise

    def _build_glassdoor_url_from_db_config(self) -> Optional[str]:
        """Build Glassdoor search URL from workflow run config in database"""
        if not self.config_reader:
            self.logger.warning("No config reader available for URL generation")
            return None

        bot_config = self.config_reader.workflow_run_config
        if not bot_config:
            self.logger.warning("No bot config available for URL generation")
            return None

        try:
            from services.jwt_token_manager import jwt_token_manager

            token = jwt_token_manager.get_token()
            headers = {"Content-Type": "application/json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"

            response = requests.post(
                f"{SERVICE_GATEWAY_URL}/api/infinite-runs/generate-platform-url",
                json={"platform": "glassdoor", "bot_config": bot_config},
                headers=headers,
                timeout=10,
            )

            if response.status_code == 200:
                result = response.json()
                if result.get("success") and result.get("url"):
                    generated_url = result["url"]
                    self.logger.info(f"Generated Glassdoor URL: {generated_url}")
                    return generated_url
                else:
                    error_msg = result.get("message", "Unknown error")
                    self.logger.error(f"URL generation failed: {error_msg}")
                    return None
            else:
                self.logger.error(
                    f"URL generation request failed with status {response.status_code}: {response.text}"
                )
                return None

        except Exception as e:
            self.logger.error(f"Exception while building Glassdoor URL: {e}")
            return None

    def _check_and_handle_login(self) -> tuple[bool, str]:
        """
        Check if sign-in is required and handle login flow
        Returns (success, error_message)
        """
        try:
            self.send_activity_message("Checking login status...")

            # Wait for page to stabilize
            time.sleep(2)

            # Check if already logged in by looking for profile button
            if self._is_logged_in():
                self.send_activity_message("Already logged in to Glassdoor")
                self.logger.info("User is already logged in")
                return True, ""

            # Check if sign-in button is present
            sign_in_button = self.bot.page.locator("button[aria-label='sign in']")
            if sign_in_button.count() > 0:
                self.send_activity_message("Please sign in to Glassdoor to continue...")
                self.logger.info("Sign-in required, waiting for user to log in")

                # Click the sign-in button to open login dialog
                self.bot.browser_operator.click_with_op(sign_in_button.first)
                time.sleep(2)

                # Wait for user to complete login (check for profile button to appear)
                max_wait_time = 300  # 5 minutes
                check_interval = 3  # Check every 3 seconds
                elapsed_time = 0

                while elapsed_time < max_wait_time:
                    if not self.bot.is_running:
                        self.logger.info("Bot stopped during login wait")
                        return False, "Bot stopped during login"

                    # Check if profile button appeared (user logged in)
                    if self._is_logged_in():
                        self.send_activity_message(
                            "Successfully logged in to Glassdoor"
                        )
                        self.logger.info("User successfully logged in")
                        time.sleep(2)  # Wait for page to stabilize after login

                        return True, ""

                    time.sleep(check_interval)
                    elapsed_time += check_interval

                    # Update user every 30 seconds
                    if elapsed_time % 30 == 0:
                        self.send_activity_message(
                            f"Still waiting for login... ({elapsed_time}s elapsed)"
                        )

                # Timeout - user didn't log in within time limit
                self.logger.error("Login timeout - user did not complete login in time")
                return False, "Login timeout - please try again"

            # No sign-in button found and not logged in - unclear state
            self.logger.info("Already logged in to Glassdoor")
            self.send_activity_message("Already logged in to Glassdoor")
            return True, ""

        except Exception as e:
            self.logger.error(f"Error during login check: {e}")
            return False, f"Login check error: {str(e)}"

    def _is_logged_in(self) -> bool:
        """Check if user is logged in to Glassdoor."""
        try:
            profile_button = self.bot.page.locator(
                "button[data-test='utility-nav-profile-button']"
            )

            if profile_button.count() > 0:
                try:
                    return profile_button.first.is_visible()
                except Exception as e:
                    self.logger.debug(f"Profile button visibility check failed: {e}")
                    return False

            return False

        except Exception as e:
            self.logger.error(f"Error checking login status: {e}")
            return False

    def _fill_search_form(self):
        """
        Fill in the Glassdoor search form with job title and location from config
        """
        try:
            self.send_activity_message("Filling in search criteria...")

            # Get job title and location from config filters
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

            # Wait for search inputs to be visible
            time.sleep(2)

            # Fill job title input using aria-labelledby selector
            job_title_input = self.bot.page.locator(
                "input[aria-labelledby='searchBar-jobTitle_label']"
            ).first
            if job_title_input.count() > 0 and job_title_input.is_visible():
                self.bot.browser_operator.fill_with_op(job_title_input, job_title)
                self.send_activity_message(f"Job title set to: {job_title}")
            else:
                self.logger.warning("Job title input not found or not visible")

            # Fill location input using aria-labelledby selector
            location_input = self.bot.page.locator(
                "input[aria-labelledby='searchBar-location_label']"
            ).first
            if location_input.count() > 0 and location_input.is_visible():
                # Click into location input
                self.bot.browser_operator.click_with_op(location_input)
                time.sleep(0.3)
                # Fill location
                self.bot.browser_operator.fill_with_op(location_input, location)
                self.send_activity_message(f"Location set to: {location}")
                time.sleep(1)  # Wait for location autocomplete
                # Press Enter to submit the search
                location_input.press("Enter")
                self.send_activity_message("Submitted Glassdoor search")
                # Wait for page to fully load after navigation
                self.bot.page.wait_for_load_state("load", timeout=30000)
                self.logger.info("Page fully loaded after search submission")
            else:
                self.logger.warning("Location input not found or not visible")

        except Exception as e:
            self.logger.error(f"Failed to fill search form: {e}")
            self.send_activity_message(f"Error filling search form: {str(e)}")

    def _maybe_close_job_alert_modal(self):
        """
        Close job alert modal if it appears after search
        """
        try:
            time.sleep(1)  # Wait for modal to potentially appear

            # Check if job alert modal is present
            close_button = self.bot.page.locator(
                "button[data-test='job-alert-modal-close']"
            )

            if close_button.count() > 0 and close_button.first.is_visible():
                self.logger.info("Job alert modal detected, closing it")
                self.send_activity_message("Closing job alert modal...")
                self.bot.browser_operator.click_with_op(close_button.first)
                time.sleep(0.5)  # Wait for modal to close
                self.logger.info("Job alert modal closed successfully")
            else:
                self.logger.debug("No job alert modal detected")

        except Exception as e:
            self.logger.warning(
                f"Failed to close job alert modal: {e} (continuing anyway)"
            )

    def _wait_for_jobs_list_container(
        self, timeout_seconds: int = 60, poll_interval: float = 2.0
    ):
        """
        Wait for the Glassdoor jobs list container to appear before processing.
        Retries until timeout_seconds is reached.
        """
        deadline = time.time() + timeout_seconds

        while time.time() < deadline:
            try:
                jobs_list_locator = self.bot.page.locator("ul[aria-label='Jobs List']")
                if jobs_list_locator.count() > 0:
                    container = jobs_list_locator.first
                    if container.count() > 0:
                        return container
            except Exception as exc:
                self.logger.debug(f"Error checking for jobs list container: {exc}")

            time.sleep(poll_interval)

        self.logger.warning(
            f"Jobs List container not found after waiting {timeout_seconds} seconds"
        )
        self.send_activity_message("No job listings found")
        return None

    def _perform_job_searching_steps(self):
        """
        Main job searching loop with infinite scroll
        Glassdoor uses infinite scroll instead of pagination
        """
        try:
            self.send_activity_message("Starting job search and queue process...")

            total_processed = 0
            total_queued = 0
            processed_indices = set()  # Track processed job card indices
            batch_number = 1
            no_new_jobs_count = 0  # Track consecutive scrolls with no new jobs

            jobs_list_container = self._wait_for_jobs_list_container()
            if not jobs_list_container:
                return

            while True:
                if not self.bot.is_running:
                    self.logger.info("Stop signal detected, halting job processing")
                    break

                # Get all job cards in the list
                job_cards_locator = jobs_list_container.locator("li")
                total_count = job_cards_locator.count()

                if total_count == 0:
                    self.logger.warning("No job cards found")
                    self.send_activity_message("No job listings found")
                    break

                # Check if we have new jobs to process
                new_jobs_count = total_count - len(processed_indices)
                if new_jobs_count == 0:
                    load_more_button = self.bot.page.locator(
                        "button[data-test*='load-more']"
                    )
                    if (
                        load_more_button.count() > 0
                        and load_more_button.first.is_visible()
                    ):
                        try:
                            self.logger.info(
                                "Load more button found, attempting to load additional jobs"
                            )
                            self.bot.browser_operator.click_with_op(
                                load_more_button.first
                            )
                            time.sleep(2)
                            job_cards_locator = jobs_list_container.locator("li")
                            total_count = job_cards_locator.count()
                            new_jobs_count = total_count - len(processed_indices)
                        except Exception as e:
                            self.logger.warning(
                                f"Failed to click load more button: {e}"
                            )

                if new_jobs_count == 0:
                    no_new_jobs_count += 1
                    if no_new_jobs_count >= 2:
                        self.logger.info("No new jobs after scrolling, search complete")
                        break
                    # Scroll down to load more jobs
                    self._scroll_jobs_list(jobs_list_container)
                    time.sleep(2)
                    continue

                # Reset no new jobs counter
                no_new_jobs_count = 0

                self.logger.info(
                    f"Batch {batch_number}: Found {new_jobs_count} new jobs "
                    f"(total: {total_count}, processed: {len(processed_indices)})"
                )
                self.send_activity_message(
                    f"Processing batch {batch_number}/{new_jobs_count} new jobs found..."
                )

                batch_processed = 0
                batch_queued = 0

                # Process only unprocessed job cards
                for index in range(total_count):
                    if index in processed_indices:
                        continue  # Skip already processed jobs

                    if not self.bot.is_running:
                        self.logger.info("Stop signal detected while processing jobs")
                        break

                    try:
                        # Re-query to avoid stale elements
                        job_cards_locator = jobs_list_container.locator("li")
                        current_count = job_cards_locator.count()

                        if current_count <= index:
                            self.logger.warning(
                                f"Job card at index {index} no longer exists"
                            )
                            continue

                        job_card = job_cards_locator.nth(index)
                        if job_card.count() == 0:
                            continue

                        # Scroll card into view within the list container
                        if not job_card.is_visible():
                            try:
                                self.bot.browser_operator.scroll_into_view_with_op(
                                    job_card, sleep_after=0.2
                                )
                            except Exception:
                                pass

                        self.logger.info(f"Processing job {index + 1}/{total_count}")

                        # Click on job card to load details
                        self.bot.browser_operator.click_with_op(job_card)
                        time.sleep(1)

                        # Extract job details
                        job_data = self._extract_job_details(job_card)

                        if not job_data.get("job_title") or not job_data.get(
                            "company_name"
                        ):
                            self.logger.warning(
                                f"Job {index + 1}: missing title/company"
                            )
                            processed_indices.add(index)
                            continue

                        batch_processed += 1

                        # Queue job for review
                        try:
                            queued = self._queue_job_for_review(job_data)
                            if queued:
                                batch_queued += 1
                        except Exception as queue_error:
                            self.logger.error(
                                f"Queueing job {index + 1} failed: " f"{queue_error}"
                            )

                        # Mark as processed
                        processed_indices.add(index)

                        time.sleep(0.5)

                    except Exception as job_error:
                        self.logger.error(
                            f"Error processing job {index + 1}: {job_error}"
                        )
                        processed_indices.add(index)
                        continue

                total_processed += batch_processed
                total_queued += batch_queued

                self.logger.info(
                    f"Batch {batch_number} completed - "
                    f"processed {batch_processed}, queued {batch_queued}"
                )
                self.send_activity_message(
                    f"Batch {batch_number} completed: "
                    f"{batch_processed} jobs processed, "
                    f"{batch_queued} jobs queued"
                )

                # Scroll down to load more jobs
                self._scroll_jobs_list(jobs_list_container)
                batch_number += 1
                time.sleep(2)

            self.logger.info(
                f"Search completed - Total batches: {batch_number}, "
                f"Total processed: {total_processed}, "
                f"Total queued: {total_queued}"
            )
            self.send_activity_message(
                f"Search completed: {batch_number} batches processed, "
                f"{total_processed} jobs evaluated, "
                f"{total_queued} jobs queued"
            )

        except Exception as e:
            self.logger.error(f"Error during job searching steps: {e}")
            raise

    def _scroll_jobs_list(self, jobs_list_container):
        """Scroll down the jobs list container to load more jobs"""
        try:
            # Scroll to bottom of the list container
            jobs_list_container.evaluate("(el) => el.scrollTop = el.scrollHeight")
            self.logger.info("Scrolled jobs list to load more")
        except Exception as e:
            self.logger.warning(f"Failed to scroll jobs list: {e}")

    def _navigate_to_next_page(self) -> bool:
        """
        Glassdoor uses infinite scroll, no pagination
        This method is kept for compatibility but always returns False
        """
        return False

    def _extract_job_details(self, job_card) -> dict:
        """Extract structured job details from the active card."""
        try:
            time.sleep(0.5)

            detail_panel_locator = self.bot.page.locator(
                "div[class*='JobDetails_jobDetailsContainer__']"
            )
            if detail_panel_locator.count() == 0:
                self.logger.warning("Job detail panel not found")
                return {}

            detail_panel = detail_panel_locator.first

            job_title = self._extract_job_title(detail_panel)
            company_name = self._extract_company_name(detail_panel)
            location = self._extract_location(detail_panel)
            pos_context = self._extract_job_description(detail_panel)
            salary_range = self._extract_salary(detail_panel)
            post_time = self._extract_post_time(job_card)
            application_url = self._extract_application_url(job_card)

            self.logger.debug(
                "Extracted Glassdoor job data - title: '%s', company: '%s', location: '%s', "
                "post_time: '%s', salary_range: %s",
                job_title,
                company_name,
                location,
                post_time,
                salary_range,
            )

            return {
                "job_title": job_title,
                "company_name": company_name,
                "location": location,
                "pos_context": pos_context,
                "salary_range": salary_range,
                "post_time": post_time,
                "application_url": application_url,
            }
        except Exception as e:
            self.logger.error(f"Failed to extract job details: {e}")
            return {}

    def _extract_job_title(self, detail_panel) -> str:
        """Extract job title."""
        try:
            title_locator = detail_panel.locator("h1")
            if title_locator.count() > 0:
                title = title_locator.first.inner_text().strip()
                if title:
                    return title

        except Exception as e:
            self.logger.warning(f"Failed to extract job title: {e}")
        return ""

    def _extract_company_name(self, detail_panel) -> str:
        """Extract company name."""
        try:
            company_locator = detail_panel.locator(
                "div[class*='EmployerProfile_employerNameHeading__']"
            )
            if company_locator.count() > 0:
                company = company_locator.first.inner_text().strip()
                if company:
                    return company
        except Exception as e:
            self.logger.warning(f"Failed to extract company name: {e}")
        return ""

    def _extract_location(self, detail_panel) -> str:
        """Extract job location."""
        try:
            location_locator = detail_panel.locator("div[data-test*='location']")
            if location_locator.count() > 0:
                location = location_locator.first.inner_text().strip()
                if location:
                    return location
        except Exception as e:
            self.logger.warning(f"Failed to extract location: {e}")
        return ""

    def _extract_job_description(self, detail_panel) -> str:
        """Extract full job description."""
        try:
            show_more_button = detail_panel.locator(
                "button[data-test*='show-more-cta']"
            )
            if show_more_button.count() > 0 and show_more_button.first.is_visible():
                try:
                    self.bot.browser_operator.click_with_op(show_more_button.first)
                    time.sleep(0.5)
                except Exception as e:
                    self.logger.debug(f"Failed to expand job description: {e}")

            desc_locator = detail_panel.locator(
                "div[class*='JobDetails_jobDescription__']"
            )
            if desc_locator.count() > 0:
                return desc_locator.first.inner_text().strip()
        except Exception as e:
            self.logger.warning(f"Failed to extract job description: {e}")
        return ""

    def _extract_salary(self, detail_panel) -> list[int]:
        """Extract salary range as [min, max] if available."""
        try:
            salary_locator = detail_panel.locator("div[data-test*='detailSalary']")
            if salary_locator.count() == 0:
                return []

            raw_text = salary_locator.first.inner_text()
            salary_text = raw_text.split("(")[0].strip()
            return self._parse_salary_range(salary_text)
        except Exception as e:
            self.logger.debug(f"Salary not available: {e}")
        return []

    def _extract_post_time(self, job_card) -> str:
        """Extract posting time as ISO string."""
        try:
            time_locator = job_card.locator("div[class*='JobCard_listingAge']")
            if time_locator.count() == 0:
                return ""

            listing_age = time_locator.first.inner_text().strip()
            if not listing_age:
                return ""

            return self._parse_post_time_text(listing_age)
        except Exception as e:
            self.logger.debug(f"Post time not available: {e}")
        return ""

    def _parse_salary_range(self, salary_text: str) -> list[int]:
        """Convert salary text like '$110K - $222K' into [min, max]."""
        if not salary_text:
            return []

        try:
            matches = re.findall(r"\$?\s*([\d.,]+)\s*([KkMm]?)", salary_text)
            if not matches:
                return []

            salaries: list[int] = []
            for value, suffix in matches:
                numeric = float(value.replace(",", ""))
                multiplier = 1
                if suffix.lower() == "k":
                    multiplier = 1_000
                elif suffix.lower() == "m":
                    multiplier = 1_000_000
                amount = int(round(numeric * multiplier))
                salaries.append(amount)

            if not salaries:
                return []

            if len(salaries) == 1:
                salaries.append(salaries[0])

            return sorted(salaries[:2])
        except Exception as e:
            self.logger.debug(f"Failed to parse salary range '{salary_text}': {e}")
            return []

    def _parse_post_time_text(self, listing_age: str) -> str:
        """Translate relative listing age into an ISO timestamp."""
        try:
            normalized = listing_age.strip().lower()
            normalized = normalized.replace("posted", "")
            normalized = normalized.replace("ago", "")
            normalized = normalized.replace("about", "")
            normalized = normalized.replace("approximately", "")
            normalized = normalized.strip()

            if not normalized:
                return ""

            if "just" in normalized or "today" in normalized:
                return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

            match = re.search(
                r"(\d+)\s*\+?\s*(minute|min|minutes|hour|hr|hours|day|d|days|week|wk|weeks|month|mo|months|year|yr|years|y|h)",
                normalized,
            )
            if not match:
                return ""

            value = int(match.group(1))
            unit = match.group(2)

            unit_map = {
                "minute": timedelta(minutes=value),
                "min": timedelta(minutes=value),
                "minutes": timedelta(minutes=value),
                "hour": timedelta(hours=value),
                "hr": timedelta(hours=value),
                "hours": timedelta(hours=value),
                "h": timedelta(hours=value),
                "day": timedelta(days=value),
                "d": timedelta(days=value),
                "days": timedelta(days=value),
                "week": timedelta(weeks=value),
                "wk": timedelta(weeks=value),
                "weeks": timedelta(weeks=value),
                "month": timedelta(days=value * 30),
                "mo": timedelta(days=value * 30),
                "months": timedelta(days=value * 30),
                "year": timedelta(days=value * 365),
                "yr": timedelta(days=value * 365),
                "years": timedelta(days=value * 365),
                "y": timedelta(days=value * 365),
            }

            delta = unit_map.get(unit)
            if not delta:
                return ""

            timestamp = datetime.utcnow() - delta
            return timestamp.replace(microsecond=0).isoformat() + "Z"
        except Exception as e:
            self.logger.debug(f"Failed to parse listing age '{listing_age}': {e}")
            return ""

    def _extract_application_url(self, job_card) -> str:
        """Extract the application URL by intercepting window.open() before clicking."""
        try:
            url = "https://www.glassdoor.com" + job_card.locator(
                "a[data-test*='job-link']"
            ).get_attribute("href")
            if not url:
                raise Exception(
                    f"Application link not found on url: {self.bot.page.url}"
                )
            return url
        except Exception as e:
            self.logger.warning(
                f"Failed to extract application link: {e}, using current page url: {self.bot.page.url}"
            )
            return self.bot.page.url

    def _queue_job_for_review(self, job_data: dict) -> bool:
        """
        Queue job for manual review in the application history.
        """
        try:
            from util.application_history_id_generator import (
                generate_application_history_id,
                generate_job_description_id,
            )

            application_url = job_data.get("application_url", "")
            if not application_url:
                self.logger.info("No application URL found, skipping job")
                return False

            app_history_id = generate_application_history_id(
                user_id=self.bot.user_id, application_url=application_url
            )
            job_desc_id = generate_job_description_id(application_url=application_url)

            existing_job = self.application_history_tracker.get_job_item_from_history(
                app_history_id
            )
            if existing_job:
                existing_status = existing_job.get("status", "unknown")

                # Check if we should skip based on status
                should_skip = True
                if (
                    existing_status == ApplicationStatus.SKIPPED.value
                    and not self.config_reader.filters.skip_previously_skipped_jobs
                ):
                    # Don't skip SKIPPED jobs if skip_previously_skipped_jobs is False
                    should_skip = False
                    self.logger.info(
                        "Reprocessing previously skipped Glassdoor job '%s' at '%s'",
                        job_data.get("job_title"),
                        job_data.get("company_name"),
                    )

                if should_skip:
                    self.logger.info(
                        "Skipping duplicate Glassdoor job '%s' at '%s' (status: %s)",
                        job_data.get("job_title"),
                        job_data.get("company_name"),
                        existing_status,
                    )
                    self.send_activity_message(
                        f"Skipping duplicate Glassdoor job '{job_data.get('job_title')}' at '{job_data.get('company_name')}' (status: {existing_status})",
                        "result",
                    )
                    return False

            position_data = {
                "job_description_id": job_desc_id,
                "application_url": application_url,
                "company_name": job_data.get("company_name", ""),
                "location": job_data.get("location", ""),
                "job_title": job_data.get("job_title", ""),
                "pos_context": job_data.get("pos_context", ""),
                "salary_range": job_data.get("salary_range", []),
                "post_time": job_data.get("post_time", ""),
                "workflow_run_id": self.workflow_run_id,
                "status": ApplicationStatus.STARTED.value,
                "job_type": job_data.get("job_type", ""),
                "num_applicants": job_data.get("num_applicants", 0),
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
            self.cur_job_data = job_data

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
                return False

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
                "Queued job for review: %s at %s",
                job_title,
                company_name,
            )
            self.logger.info(
                "Sending queued message with status: %s, thread: %s",
                self.activity_manager.current_thread_status,
                self.activity_manager.current_thread_title,
            )
            self.send_activity_message(f"Queued: {company_name} | {job_title}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to queue job: {e}")
            return False

    def maybe_skip_application(self):
        """
        Check if we should skip this application.
        Returns True if we should skip, False if we should proceed.
        """
        from services.ai_engine_client import AIEngineClient  # noqa: E402
        from shared.interest_marker import InterestMarker  # noqa: E402
        from shared.interest_marker.defs import JobData  # noqa: E402

        company_name = self.cur_job_data.get("company_name", "Unknown Company")
        job_title = self._clean_job_title(
            self.cur_job_data.get("job_title", "Unknown Position")
        )

        app_history_id = self.application_history_tracker.cur_recording_app_history_id
        if app_history_id:
            existing_job = self.application_history_tracker.get_job_item_from_history(
                app_history_id
            )
            if (
                existing_job
                and existing_job.get("status") == ApplicationStatus.REMOVED.value
            ):
                self.send_activity_message(
                    f"Skipping {company_name} | {job_title} (manually removed)",
                    "action",
                )
                self.activity_manager.start_application_thread(
                    company_name, job_title, ApplicationStatus.REMOVED.value
                )
                return True

        self.activity_manager.start_application_thread(
            company_name, job_title, "Started"
        )
        self.send_activity_message(f"Evaluating {company_name} | {job_title}", "action")

        (
            blacklist_companies_str,
            job_search_criteria,
        ) = self._get_user_filters_from_supabase()

        self.send_activity_message(f"Checking blacklist for {company_name}", "action")
        self.logger.info(
            f"Checking if company {self.cur_job_data['company_name']} is a good match"
        )

        def is_in_blacklist(company: str) -> tuple[bool, str]:
            system = f"""
            You have a blacklist of companies that you do not want to apply to.
            Blacklist: {blacklist_companies_str}
            """
            if company.lower() in blacklist_companies_str.lower():
                return True, "Company is in the blacklist"

            prompt = f"Is this company in the blacklist? {company}"
            schema = {
                "type": "object",
                "properties": {
                    "answer": {
                        "type": "boolean",
                        "description": "Whether the company is in the blacklist",
                    },
                    "thinking": {
                        "type": "string",
                        "description": (
                            "Explain concisely your reasoning "
                            "to convince me your answer"
                        ),
                    },
                },
                "required": ["answer"],
            }

            ai_client = AIEngineClient()
            response = ai_client.call_ai(prompt=prompt, system=system, format=schema)

            if response is None:
                self.logger.warning(
                    "AI engine returned None, defaulting to not blacklisted"
                )
                msg = "AI engine unavailable, defaulting to not blacklisted"
                return False, msg

            is_blacklisted = response.get("answer", False)
            thinking = response.get("thinking", "")
            if thinking and is_blacklisted:
                self.logger.info(f"AI Thinking: {thinking}")
            self.logger.info(f"is_in_blacklist: {is_blacklisted}")
            return is_blacklisted, thinking

        def is_a_good_match(job_info: JobData) -> tuple[bool, str]:
            interest_marker = InterestMarker(
                job_info,
                job_search_criteria,
                display_thinking_callback=self.maybe_display_activity,
            )
            company = self.cur_job_data.get("company_name", "")
            title = self.cur_job_data.get("job_title", "")
            self.logger.info(
                f"Checking if {company} - {title} matches what you are looking for"
            )
            try:
                alignments, should_skip, reasoning = interest_marker.run()
            except Exception as e:
                self.logger.warning(f"Interest marker failed: {e}, defaulting to apply")
                alignments, should_skip, reasoning = (
                    None,
                    False,
                    "Interest marker unavailable, defaulting to apply",
                )
            should_skip = False  # Temporary until interest marker is finalized

            if not should_skip:
                app_id = self.application_history_tracker.cur_recording_app_history_id
                if app_id and alignments:
                    self.application_history_tracker.update_application(
                        app_id,
                        "criteria_alignment",
                        [alignment.to_dict() for alignment in alignments],
                    )

            company = self.cur_job_data.get("company_name", "")
            title = self.cur_job_data.get("job_title", "")
            company_title = f"{company} - {title}"
            formatted_alignments = (
                interest_marker.format_alignments(alignments) if alignments else ""
            )
            message = f"The position matches your criteria. Applying to {company_title}"
            if should_skip:
                message = f"Skipping {company_title} due to not a good match"
            if formatted_alignments:
                message += f"\n\n{formatted_alignments}"
            self.logger.info(message)
            return should_skip, reasoning

        def _is_existing_staffing_company(company: str) -> tuple[bool, str]:
            if not self.config_reader.filters.skip_staffing_companies:
                return False, "Staffing company check is disabled"

            if not self.config_reader.filters.staffing_companies:
                return False, "No staffing companies list loaded"

            company_lower = company.lower()
            staffing_list = self.config_reader.filters.staffing_companies
            if company_lower in staffing_list:
                return True, f"{company} is a known staffing company"

            return False, f"{company} is not in the staffing companies list"

        try:
            is_existing_staffing, thinking = _is_existing_staffing_company(
                self.cur_job_data["company_name"]
            )
        except Exception as e:
            msg = (
                f"Existing staffing company check failed: {e}, "
                f"defaulting to not staffing"
            )
            self.logger.warning(msg)
            is_existing_staffing, thinking = (
                False,
                "Staffing company check unavailable, defaulting to not staffing",
            )

        if is_existing_staffing:
            if thinking:
                self.send_activity_message(f"Analysis: {thinking}", "thinking")

            skip_reason = (
                f"Skipping {company_name} | {job_title} (known staffing company)"
            )
            self.send_activity_message(skip_reason, "result")
            self.activity_manager.update_application_status(
                ApplicationStatus.SKIPPED.value
            )
            return True

        if self.config_reader.filters.skip_staffing_companies:
            is_new_staffing = self._check_if_staffing_company()
            if is_new_staffing:
                self.logger.info(
                    "Skipping application - AI detected new staffing company"
                )
                skip_reason = (
                    f"Skipping {company_name} | {job_title} (staffing company)"
                )
                self.send_activity_message(skip_reason, "result")
                self.activity_manager.update_application_status(
                    ApplicationStatus.SKIPPED.value
                )
                return True

        try:
            in_blacklist, thinking = is_in_blacklist(self.cur_job_data["company_name"])
        except Exception as e:
            self.logger.warning(
                f"Blacklist check failed: {e}, defaulting to not blacklisted"
            )
            in_blacklist, thinking = (
                False,
                "Blacklist check unavailable, defaulting to not blacklisted",
            )

        if in_blacklist:
            if thinking:
                self.send_activity_message(f"AI Analysis: {thinking}", "thinking")

            skip_reason = f"Skipping {company_name} | company is blacklisted"
            self.send_activity_message(skip_reason, "result")
            self.activity_manager.update_application_status(
                ApplicationStatus.SKIPPED.value
            )
            return True

        msg = f"{company_name} not found in blacklist - proceeding"
        self.send_activity_message(msg, "result")
        self.send_activity_message(
            f"Checking job criteria match for {company_name}", "action"
        )

        job_payload = JobData(
            job_title=self.cur_job_data.get("job_title", ""),
            job_description=self.cur_job_data.get("pos_context", ""),
            company_name=self.cur_job_data.get("company_name", ""),
            post_time=self.cur_job_data.get("post_time", ""),
            location=self.cur_job_data.get("location", ""),
        )
        try:
            should_skip, think = is_a_good_match(job_payload)
            matched = not should_skip
        except Exception as e:
            self.logger.warning(f"Job matching failed: {e}, defaulting to apply")
            should_skip, think = (
                False,
                "Job matching unavailable, defaulting to apply",
            )
            matched = True

        if not matched:
            if think:
                self.send_activity_message(f"AI Analysis: {think}", "thinking")

            msg = f"Skipping {company_name} | doesn't match job criteria"
            self.send_activity_message(msg, "result")

            log_msg = (
                f"Skipping application because it's not a good match: "
                f"{self.cur_job_data['company_name']}"
            )
            self.logger.info(log_msg)
            if think:
                self.logger.debug(f"Skip reason: Not a good match - {think}")
            self.activity_manager.update_application_status(
                ApplicationStatus.SKIPPED.value
            )
            return True

        if think:
            self.send_activity_message(f"AI Analysis: {think}", "thinking")

        msg = f"{company_name} matches job criteria - proceeding to ATS analysis"
        self.send_activity_message(msg, "result")
        self.analyze_ats_score(job_payload)
        return False

    def maybe_display_activity(self, text: str):
        """Display activity callback for AI thinking"""
        self.send_activity_message(f"AI Thinking: {text}", "thinking")

    def analyze_ats_score(self, job_data):
        """
        Analyze ATS score using ATSMarker service.
        """
        from shared.ats_marker import ATSMarker  # noqa: E402
        from shared.ats_marker.defs import ApplicantData  # noqa: E402

        additional_skills = self.config_reader.profile.additional_experience or ""

        log_msg = (
            f"Using additional skills from ATS template for ATS analysis: "
            f"{len(additional_skills)} characters"
        )
        logger.info(log_msg)
        if additional_skills:
            logger.debug(
                f"ATS template additional skills content: "
                f"{additional_skills[:200]}..."
            )
        else:
            logger.info(
                "No additional experience found in ATS template - using resume only"
            )

        applicant_data = ApplicantData(
            resume=self.config_reader.profile.resume,
            additional_skills_and_experience=additional_skills,
            selected_ats_template_id=(
                self.config_reader.profile.selected_ats_template_id
            ),
        )

        from constants import SERVICE_GATEWAY_URL  # noqa: E402
        from services.jwt_token_manager import jwt_token_manager  # noqa: E402

        user_token = jwt_token_manager.get_token()
        if not user_token:
            self.logger.warning("No JWT token available for ATS analysis")

        ats_marker = ATSMarker(
            job_data=job_data,
            applicant_data=applicant_data,
            bot=self,
            display_thinking_callback=self.maybe_display_activity,
            alignment_score_threshold=0.8,
            service_gateway_url=SERVICE_GATEWAY_URL,
            user_token=user_token,
        )

        company_name = job_data.company_name
        msg = f"Running ATS analysis for {company_name}"
        self.send_activity_message(msg, "action")

        self.logger.info(
            f"Analyzing ATS score for {job_data.company_name} - "
            f"{job_data.job_title}"
        )

        try:
            score, alignments, keywords_to_add = ats_marker.run()

            self.cur_job_data["initial_ats_score"] = score
            self.cur_job_data["initial_ats_alignments"] = [
                alignment.to_dict() for alignment in alignments
            ]
            self.cur_job_data["keywords_to_add"] = keywords_to_add

            missing_requirements = []
            for alignment in alignments:
                if alignment.alignment_score < alignment.max_score * 0.8:
                    missing_requirements.append(alignment.to_dict())
            self.cur_job_data["missing_requirements"] = missing_requirements

            log_msg = (
                f"Stored ATS analysis in cur_job_data: score={score}, "
                f"alignments={len(alignments)}, "
                f"missing={len(missing_requirements)}"
            )
            self.logger.info(log_msg)

            if self.application_history_tracker.cur_recording_app_history_id:
                cur_id = self.application_history_tracker.cur_recording_app_history_id
                self.application_history_tracker.update_application(
                    cur_id,
                    "ats_score",
                    score,
                )
                self.application_history_tracker.update_application(
                    cur_id,
                    "ats_alignments",
                    [alignment.to_dict() for alignment in alignments],
                )
                self.application_history_tracker.update_application(
                    cur_id,
                    "ats_keyword_to_add_to_resume",
                    keywords_to_add,
                )
                self.application_history_tracker.sync_application_history()

            formatted_results = ats_marker.format_alignments(score, alignments)
            if formatted_results:
                self.send_activity_message(f"{formatted_results}", "thinking")

            if score >= 70:
                score_msg = f"ATS Score: {score}/100 - Strong resume match!"
                self.send_activity_message(score_msg, "result")
                self.logger.info(
                    f"Good ATS score: {score}/100 - Resume aligns well with job requirements"
                )
            elif score >= 50:
                score_msg = f"ATS Score: {score}/100 - Moderate match"
                self.send_activity_message(score_msg, "result")
                self.logger.info(
                    f"Moderate ATS score: {score}/100 - Some improvements possible"
                )
            else:
                score_msg = f"ATS Score: {score}/100 - Weak resume match"
                self.send_activity_message(score_msg, "result")
                self.logger.info(
                    f"Low ATS score: {score}/100 - Significant gaps in requirements"
                )

            self.logger.info(f"ATS Analysis Results:\n{formatted_results}")

            if keywords_to_add:
                suggestions = ", ".join(keywords_to_add[:3])
                ellipsis = "..." if len(keywords_to_add) > 3 else ""
                self.send_activity_message(
                    f"ATS Keywords Suggestions: {suggestions}{ellipsis}", "result"
                )
                keywords_str = ", ".join(keywords_to_add)
                log_msg = "Suggested keywords to improve ATS score: " f"{keywords_str}"
                self.logger.info(log_msg)

            if (
                self.config_reader.settings.generate_ats_optimized_resume
                and self.config_reader.profile.ats_resume_template
            ):
                self.logger.info("Generating ATS-optimized resume for queued job...")
                self.send_activity_message(
                    "Generating ATS-optimized resume...", "action"
                )
                optimized_resume_path = self._generate_ats_optimized_resume()

                if optimized_resume_path:
                    msg = "ATS-optimized resume generated successfully"
                    self.send_activity_message(msg, "result")
                    self.logger.info(msg)
                else:
                    msg = "Failed to generate ATS-optimized resume"
                    self.send_activity_message(msg, "result")
                    self.logger.warning(msg)

        except Exception as e:
            self.logger.error(f"Error during ATS analysis: {e}")
            self.logger.info("ATS analysis failed, but proceeding with application")

    def _get_user_filters_from_supabase(self):
        """
        Read user's blacklist companies and job search criteria from
        config_reader (which uses platform_filters).
        Returns tuple of (blacklist_companies_str, job_search_criteria_str).
        """
        try:
            # Get blacklist companies from config_reader filters
            blacklist_companies = self.config_reader.filters.blacklist_companies
            if isinstance(blacklist_companies, list):
                blacklist_companies = ", ".join(blacklist_companies)
            else:
                blacklist_companies = (
                    str(blacklist_companies) if blacklist_companies else ""
                )

            # Get job search criteria from config_reader (uses platform_filters)
            job_search_criteria = self.config_reader.get_job_search_criteria_string()

            blacklist_preview = blacklist_companies[:50]
            blacklist_ellipsis = "..." if len(blacklist_companies) > 50 else ""
            log_msg = (
                f"Loaded filters - Blacklist: "
                f"{blacklist_preview}{blacklist_ellipsis}"
            )
            self.logger.info(log_msg)

            criteria_preview = job_search_criteria[:100]
            criteria_ellipsis = "..." if len(job_search_criteria) > 100 else ""
            log_msg = f"Job criteria: {criteria_preview}{criteria_ellipsis}"
            self.logger.info(log_msg)

            return blacklist_companies or "", job_search_criteria

        except Exception as e:
            self.logger.error(f"Error reading filters: {e}")
            # Return sensible defaults if reading fails
            default_criteria = "software engineer, python, remote work"
            return "Facebook, Meta, Amazon", default_criteria

    def _check_if_staffing_company(self) -> bool:
        """
        Check for staffing companies using AI (disabled like Indeed).
        """
        self.logger.debug(
            "Glassdoor bot skipping AI staffing company check - using known list only"
        )
        return False

    def _generate_ats_optimized_resume(self) -> Optional[str]:
        """
        Generate ATS-optimized resume for the queued job.
        """
        try:
            import tempfile
            from pathlib import Path

            import requests

            from constants import SERVICE_GATEWAY_URL
            from services.jwt_token_manager import jwt_token_manager

            job_description = self.cur_job_data.get("pos_context", "")
            if not job_description:
                msg = "No job description available for ATS optimization"
                logger.warning(msg)
                return None

            additional_skills = self.config_reader.profile.additional_experience or ""
            template_html = self.config_reader.profile.ats_resume_template

            log_msg = (
                f"Using additional skills from ATS template for resume "
                f"generation: {len(additional_skills)} characters"
            )
            logger.info(log_msg)

            if not template_html:
                logger.warning("No ATS template HTML available")
                return None

            token = jwt_token_manager.get_token()
            if not token:
                msg = "No JWT token available for ATS resume generation"
                logger.warning(msg)
                return None

            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            base_url = f"{SERVICE_GATEWAY_URL}/api/ats"

            initial_ats_score = self.cur_job_data.get("initial_ats_score", 0)
            initial_ats_alignments = self.cur_job_data.get("initial_ats_alignments", [])
            keywords_to_add = self.cur_job_data.get("keywords_to_add", [])
            missing_requirements = self.cur_job_data.get("missing_requirements", [])

            msg = f"Initial ATS Score: {initial_ats_score}/100"
            self.send_activity_message(msg, "result")

            self.send_activity_message(
                "Analyzing additional skills for missing requirements...", "action"
            )

            skills_check_payload = {
                "missing_requirements": missing_requirements,
                "additional_skills_and_experience": additional_skills,
            }

            skills_response = requests.post(
                f"{base_url}/check-additional-skills",
                headers=headers,
                json=skills_check_payload,
            )

            if skills_response.status_code != 200:
                logger.error(
                    f"Skills check failed: {skills_response.status_code} - {skills_response.text}"
                )
                return None

            skills_result = skills_response.json()
            if not skills_result.get("success"):
                logger.error(f"Skills check failed: {skills_result}")
                return None

            addressable_requirements = skills_result.get("addressable_requirements", [])
            skills_check_thinking = skills_result.get("thinking", "")
            total_missing = len(missing_requirements)
            total_addressable = len(addressable_requirements)

            self.send_activity_message(
                f"Found {total_addressable}/{total_missing} addressable requirements",
                "result",
            )

            self.send_activity_message(
                "Generating optimized resume content...", "action"
            )

            app_id = self.application_history_tracker.cur_recording_app_history_id
            template_id = self.config_reader.profile.selected_ats_template_id
            create_resume_payload = {
                "ats_template_id": template_id,
                "template_html": template_html,
                "job_description": job_description,
                "job_url": self.cur_job_data.get("application_url", ""),
                "initial_ats_score": initial_ats_score,
                "initial_ats_alignments": initial_ats_alignments,
                "keywords_to_add": keywords_to_add,
                "addressable_requirements": addressable_requirements,
                "skills_check_thinking": skills_check_thinking,
                "additional_skills_and_experience": additional_skills,
                "missing_requirements": missing_requirements,
                "total_missing": total_missing,
                "total_addressable": total_addressable,
                "application_history_id": app_id,
            }

            create_response = requests.post(
                f"{SERVICE_GATEWAY_URL}/api/ats-resume",
                headers=headers,
                json=create_resume_payload,
            )

            if create_response.status_code != 200:
                log_msg = (
                    f"Resume creation failed: {create_response.status_code} - "
                    f"{create_response.text}"
                )
                logger.error(log_msg)
                return None

            create_result = create_response.json()
            if not create_result.get("success") or not create_result.get(
                "ats_resume_id"
            ):
                logger.error(f"Resume creation failed: {create_result}")
                return None

            ats_resume_id = create_result["ats_resume_id"]
            optimized_html = create_result.get("optimized_html")

            logger.info(f"ATS resume created with ID: {ats_resume_id}")

            if not optimized_html:
                logger.error("No optimized HTML returned from resume creation")
                return None

            self.send_activity_message("Validating improvements...", "action")

            from bs4 import BeautifulSoup

            from shared.ats_marker import ATSMarker
            from shared.ats_marker.defs import ApplicantData, JobData

            soup = BeautifulSoup(optimized_html, "html.parser")
            optimized_resume_text = soup.get_text()

            final_job_data = JobData(
                job_title=self.cur_job_data.get("job_title", ""),
                job_description=job_description,
                company_name=self.cur_job_data.get("company_name", ""),
                post_time=self.cur_job_data.get("post_time", ""),
                location=self.cur_job_data.get("location", ""),
            )

            final_applicant_data = ApplicantData(
                resume=optimized_resume_text,
                additional_skills_and_experience=additional_skills,
            )

            final_ats_marker = ATSMarker(
                final_job_data,
                final_applicant_data,
                user_token=token,
            )

            try:
                final_ats_score, final_alignments_objects, _ = final_ats_marker.run()

                final_ats_alignments = []
                for alignment in final_alignments_objects:
                    final_ats_alignments.append(
                        {
                            "requirement": alignment.requirement.description,
                            "alignment_score": alignment.alignment_score,
                            "reason": alignment.reason,
                        }
                    )

                ats_improvement = final_ats_score - initial_ats_score

                msg = (
                    f"Final ATS Score: {final_ats_score}/100 "
                    f"(Improvement: +{ats_improvement})"
                )
                self.send_activity_message(msg, "result")

            except Exception as e:
                logger.error(f"Final ATS analysis failed: {e}")
                final_ats_score = initial_ats_score
                final_ats_alignments = []
                ats_improvement = 0

                msg = (
                    f"Final validation failed, using initial score: "
                    f"{final_ats_score}/100"
                )
                self.send_activity_message(msg, "result")

            if app_id:
                updates = {
                    "ats_score": initial_ats_score,
                    "ats_alignments": initial_ats_alignments,
                    "ats_keyword_to_add_to_resume": keywords_to_add,
                    "optimized_ats_score": final_ats_score,
                    "optimized_ats_alignments": final_ats_alignments,
                    "missing_requirements": missing_requirements,
                    "addressable_requirements": addressable_requirements,
                    "skills_check_thinking": skills_check_thinking,
                    "ats_resume_id": ats_resume_id,
                    "ats_template_id": template_id,
                }

                for field, value in updates.items():
                    self.application_history_tracker.update_application(
                        app_id, field, value
                    )

                self.application_history_tracker.sync_application_history()
                logger.info(
                    f"Stored complete ATS analysis in application history: {app_id}"
                )

            self.send_activity_message(
                "Converting optimized resume to PDF...", "action"
            )

            from util.pdf_generator import generate_pdf_from_html

            temp_dir = Path(tempfile.mkdtemp())
            company_slug = (
                self.cur_job_data.get("company_name", "").replace(" ", "_").lower()
            )
            job_slug = self.cur_job_data.get("job_title", "").replace(" ", "_").lower()
            pdf_filename = f"optimized_resume_{company_slug}_{job_slug}"

            try:
                optimized_pdf_path = generate_pdf_from_html(
                    html_content=optimized_html,
                    output_dir=temp_dir,
                    filename=pdf_filename,
                )

                if optimized_pdf_path and optimized_pdf_path.exists():
                    logger.info(f"Generated optimized resume PDF: {optimized_pdf_path}")

                    self.send_activity_message(
                        "Uploading optimized resume to cloud storage...", "action"
                    )

                    try:
                        blob_url = self._upload_pdf_to_blob_storage(
                            optimized_pdf_path, ats_resume_id
                        )

                        if blob_url:
                            logger.info(f"Uploaded PDF to blob storage: {blob_url}")

                            success = self._update_ats_resume_blob_url(
                                ats_resume_id, blob_url
                            )
                            if success:
                                logger.info(
                                    f"Updated ATS resume {ats_resume_id} with blob_url"
                                )
                            else:
                                logger.warning(
                                    "Failed to update ATS resume with blob_url"
                                )
                        else:
                            logger.warning("Failed to upload PDF to blob storage")

                    except Exception as upload_error:
                        logger.error(
                            f"Error uploading PDF to blob storage: {upload_error}"
                        )

                    return str(optimized_pdf_path)
                else:
                    logger.error("Failed to generate optimized resume PDF")
                    return None
            except Exception as e:
                logger.error(f"Error generating PDF: {e}")
                return None

        except Exception as e:
            logger.error(f"Error generating ATS-optimized resume: {e}")
            import traceback

            logger.error(f"Traceback: {traceback.format_exc()}")
            return None

    def _upload_pdf_to_blob_storage(self, pdf_path: str, ats_resume_id: str) -> str:
        """Upload generated PDF to blob storage via service gateway."""
        try:
            import requests

            from constants import SERVICE_GATEWAY_URL
            from services.jwt_token_manager import jwt_token_manager

            token = jwt_token_manager.get_token()
            if not token:
                logger.warning("No JWT token for blob upload")
                return ""

            with open(pdf_path, "rb") as file_obj:
                pdf_content = file_obj.read()

            files = {"file": ("resume.pdf", pdf_content, "application/pdf")}
            headers = {"Authorization": f"Bearer {token}"}

            response = requests.post(
                f"{SERVICE_GATEWAY_URL}/api/ats-resume/{ats_resume_id}/upload",
                headers=headers,
                files=files,
            )

            if response.status_code == 200:
                result = response.json()
                return result.get("blob_url", "")

            logger.error(f"Upload failed: {response.status_code} - {response.text}")
            return ""

        except Exception as e:
            logger.error(f"Error uploading PDF: {e}")
            return ""

    def _update_ats_resume_blob_url(self, ats_resume_id: str, blob_url: str) -> bool:
        """Update ATS resume record with blob URL."""
        try:
            import requests

            from constants import SERVICE_GATEWAY_URL
            from services.jwt_token_manager import jwt_token_manager

            token = jwt_token_manager.get_token()
            if not token:
                logger.warning("No JWT token for ATS resume update")
                return False

            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }

            payload = {"blob_url": blob_url}

            response = requests.put(
                f"{SERVICE_GATEWAY_URL}/api/ats-resume/{ats_resume_id}",
                headers=headers,
                json=payload,
            )

            return response.status_code == 200

        except Exception as e:
            logger.error(f"Error updating ATS resume: {e}")
            return False

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
