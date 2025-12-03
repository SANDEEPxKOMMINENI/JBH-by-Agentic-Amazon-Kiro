#!/usr/bin/env python3
"""
Start Searching Action for Dice Bot
"""

import logging
import os
import random
import sys
import time
import traceback
from typing import Any, Dict, Optional

import requests

# Add parent directories to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from browser.browser_operator import BrowserOperator
from constants import SERVICE_GATEWAY_URL
from dice_bot.actions.base_action import BaseAction
from shared.models.application_history import ApplicationStatus
from util.application_history_id_generator import (
    generate_application_history_id,
    generate_job_description_id,
)

logger = logging.getLogger(__name__)


class StartSearchingAction(BaseAction):
    """Action to start the Dice job searching and queueing process"""

    def __init__(self, bot_instance):
        super().__init__(bot_instance)
        self.workflow_run_id = bot_instance.workflow_run_id
        self.cur_job_data = {}  # Current job data for maybe_skip_application

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
        # Remove common Dice job post suffixes if any
        suffixes_to_remove = [" - job post", "- job post", " -job post", "-job post"]
        cleaned = job_title
        for suffix in suffixes_to_remove:
            if cleaned.endswith(suffix):
                cleaned = cleaned[: -len(suffix)].strip()
        return cleaned

    def execute(self) -> Dict[str, Any]:
        """
        Start the Dice searching process
        Returns status dict with success/error info
        """
        try:
            self.logger.info(f"Starting Dice bot {self.bot.bot_id}")

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

            # Initialize config reader and application history tracker FIRST
            self._init_trackers()

            # Navigate to Dice homepage
            self.bot.current_url = self._navigate_to_dice_sync()
            self.send_activity_message("Opened Dice homepage")

            # Generate search URL with AI and navigate to it
            time.sleep(5)
            built_url = self._build_dice_url_from_db_config()
            if built_url:
                self.send_activity_message(f"Opening Dice search page: `{built_url}`")
                self.bot.current_url = self.bot.browser_operator.navigate_to(built_url)
                time.sleep(3)  # Wait for search results to load
            else:
                self.logger.error("Failed to build Dice URL from config")
                return {
                    "success": False,
                    "message": "Failed to build Dice URL from config",
                    "status": "error",
                }

            self.send_status_update(
                "running", "Successfully launched and navigated to Dice"
            )

            # Perform job searching steps
            time.sleep(5)
            self._perform_job_searching_steps()

            # After completing the search, automatically stop the bot
            self.logger.info(
                f"Dice bot {self.bot.bot_id} completed job searching batch"
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
                "message": "Dice bot completed job searching batch successfully",
                "status": "completed",
                "current_url": self.bot.current_url,
            }

        except Exception as e:
            self.logger.error(f"Failed to start Dice bot in execute: {e}")

            traceback.print_exc()

            # Cleanup on error
            self._cleanup_on_error()

            self.send_status_update("error", f"Failed to start: {str(e)}")

            return {
                "success": False,
                "message": f"Failed to start Dice bot in execute: {str(e)}",
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

    def _navigate_to_dice_sync(self) -> str:
        """Navigate to Dice homepage"""
        try:
            url = "https://www.dice.com/jobs"
            current_url = self.bot.browser_operator.navigate_to(url)
            time.sleep(2)  # Wait for page to stabilize
            return current_url
        except Exception as e:
            self.logger.error(f"Failed to navigate to Dice: {e}")
            raise

    def _build_dice_url_from_db_config(self) -> Optional[str]:
        """Build Dice search URL from workflow run config in database"""
        if not self.config_reader:
            self.logger.info("ConfigReader not initialized, cannot build Dice URL")
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
                json={"platform": "dice", "bot_config": bot_config},
                headers=headers,
                timeout=10,
            )

            if response.status_code == 200:
                result = response.json()
                if result.get("success") and result.get("url"):
                    built_url = result["url"]
                    self.logger.info(f"Successfully built Dice URL: {built_url}")
                    return built_url
                else:
                    error_msg = result.get("error", "Unknown error")
                    self.logger.error(f"Failed to build Dice URL: {error_msg}")
                    return None
            else:
                self.logger.error(
                    f"Service-gateway returned error "
                    f"{response.status_code}: {response.text}"
                )
                return None

        except Exception as e:
            self.logger.error(f"Exception while building Dice URL: {e}")
            return None

    def _fill_search_form(self):
        """Fill in the Dice search form with job title and location from config"""
        try:
            self.send_activity_message("Filling in search criteria...")

            # Get job title and location from config filters
            job_title = self.config_reader.filters.job_description or ""
            location = self.config_reader.filters.location or ""

            if not job_title:
                self.logger.warning(
                    f"Missing search criteria - job_title: '{job_title}'"
                )
                self.send_activity_message(
                    "Warning: Missing job title or location in config"
                )
                return

            job_title_entered = False
            location_entered = False
            location_for_submit = None

            def press_enter():
                return self.bot.page.keyboard.press("Enter")

            # Updated Dice UI: try aria-label driven inputs
            job_title_alt = self.bot.page.locator(
                "input[aria-label*='Job title, skill, company, keyword']"
            )
            if job_title_alt.count() > 0:
                job_title_candidate = job_title_alt.first
                if job_title_candidate.is_visible():
                    self.bot.browser_operator.fill_with_op(
                        job_title_candidate, job_title
                    )
                    self.bot.browser_operator.op(press_enter)
                    self.send_activity_message(f"Job title set to: {job_title}")
                    self.logger.info("Filled job title using aria-label selector")
                    job_title_entered = True
                else:
                    self.logger.warning("Aria-label job title input not visible")
            else:
                self.logger.warning("Aria-label job title input not found")

            location_alt = self.bot.page.locator("input[aria-label*='Location Field']")
            if location_alt.count() > 0:
                location_candidate = location_alt.first
                if location_candidate.is_visible():
                    self.bot.browser_operator.fill_with_op(location_candidate, location)
                    location_for_submit = location_candidate

                    def focus_location():
                        return location_candidate.focus()

                    self.bot.browser_operator.op(focus_location)
                    self.send_activity_message(f"Location set to: {location}")
                    self.logger.info("Filled location using aria-label selector")
                    location_entered = True
                else:
                    self.logger.warning("Aria-label location input not visible")
            else:
                self.logger.warning("Aria-label location input not found")

            if not job_title_entered:
                self.send_activity_message("Warning: Unable to set job title field")
                return

            if not location_entered:
                self.send_activity_message("Warning: Unable to set location field")
                return

            if job_title_entered and location_entered:
                if location_for_submit:

                    def refocus_location():
                        return location_for_submit.focus()

                    self.bot.browser_operator.op(refocus_location)
                self.bot.browser_operator.op(press_enter)
                self.send_activity_message("Started job search")
                time.sleep(3)  # Wait for search results to load
                self.logger.info("Triggered search using Enter key")
                return

        except Exception as e:
            self.logger.error(f"Failed to fill search form: {e}")
            self.send_activity_message(f"Error filling search form: {str(e)}")

    def _perform_job_searching_steps(self):
        """Main job searching loop - process jobs across all pages"""
        try:
            # scroll area is self.bot.page.locator("div[aria-label*='Job search results']")., scroll it down to render all widgets
            # then get all apply buttons by  self.bot.page.locator("div[aria-label*='Job search results']").locator("a", has_text="Apply")
            # open a new page by click on each of the button to open and view the job details
            #

            self.send_activity_message("Starting job search and queue process...")

            # Import the position info extractor
            from dice_bot.position_info_extractor import PositionInfoExtractor

            page_number = 1
            total_processed = 0
            total_queued = 0

            # Loop through all pages
            while True:
                # Check stop signal at start of each page
                if not self.bot.is_running:
                    self.logger.info("Stop signal detected, halting job processing")
                    break

                self.logger.info(f"Processing page {page_number}")
                self.send_activity_message(f"Processing page {page_number}...")

                # Step 1: Locate the Dice results container
                results_container_locator = self.bot.page.locator(
                    "div[aria-label*='Job search results']"
                )
                if results_container_locator.count() == 0:
                    self.logger.warning("Job search results container not found")
                    self.send_activity_message("No job results found")
                    break

                results_container = results_container_locator.first

                if not results_container.is_visible():
                    try:
                        self.bot.browser_operator.scroll_into_view_with_op(
                            results_container, sleep_after=0.5
                        )
                    except Exception as scroll_error:
                        self.logger.warning(
                            f"Could not bring results container into view: {scroll_error}"
                        )

                # Step 2: Scroll within the results container to load all listings
                self._scroll_job_cards()

                # Step 3: Collect all Apply buttons within the results container
                apply_buttons_locator = results_container.locator("a", has_text="Apply")
                apply_locators: list[Any] = []
                apply_count = apply_buttons_locator.count()
                for idx in range(apply_count):
                    locator = apply_buttons_locator.nth(idx)
                    try:
                        if locator.is_visible():
                            apply_locators.append(locator)
                    except Exception as visibility_error:
                        self.logger.debug(
                            f"Skipping apply locator at index {idx}: {visibility_error}"
                        )

                total_count = len(apply_locators)
                self.logger.info(f"Apply buttons found on page: {total_count}")
                self.send_activity_message(
                    f"Loaded {total_count} apply-ready listings, processing..."
                )

                if total_count == 0:
                    self.logger.warning("No apply buttons found on this page")
                    self.send_activity_message("No apply buttons found on this page")

                # Step 4: Process each Apply button to extract job information
                page_processed_count = 0
                page_queued_count = 0

                for index, apply_button in enumerate(apply_locators, 1):
                    try:
                        # Check stop signal
                        if not self.bot.is_running:
                            self.logger.info(
                                "Stop signal detected, halting job processing"
                            )
                            break

                        self.logger.info(
                            f"Processing apply button {index}/{total_count}"
                        )

                        # Bring apply button into view before interacting
                        try:
                            self.bot.browser_operator.scroll_into_view_with_op(
                                apply_button, sleep_after=0.3
                            )
                        except Exception as scroll_error:
                            self.logger.debug(
                                f"Unable to scroll apply button into view: {scroll_error}"
                            )

                        context = self.bot.browser_operator.context
                        main_page = self.bot.page
                        new_page = None

                        if context is None:
                            self.logger.error(
                                "Browser context is unavailable; cannot open job detail page"
                            )
                            continue

                        try:
                            with context.expect_page(timeout=100000) as new_page_info:
                                self.bot.browser_operator.click_with_op(apply_button)
                            new_page = new_page_info.value
                        except Exception as page_error:
                            self.logger.error(
                                f"Failed to open job detail page for apply button {index}: {page_error}"
                            )
                            continue

                        if new_page is None or new_page.is_closed():
                            self.logger.warning(
                                f"Apply button {index} did not open a new page or page closed immediately"
                            )
                            continue

                        job_info: dict[str, Any] = {}
                        detail_url = ""

                        try:
                            new_page.wait_for_load_state(
                                "domcontentloaded", timeout=15000
                            )
                            detail_url = new_page.url
                        except Exception as load_error:
                            self.logger.warning(
                                f"Timeout waiting for job detail page to load (job {index}): {load_error}"
                            )
                            try:
                                detail_url = new_page.url
                            except Exception:
                                detail_url = ""

                        # Check for description toggle button and click it to show full job description
                        try:
                            toggle_button = new_page.locator(
                                "button[id*=descriptionToggle]"
                            )
                            if (
                                toggle_button.count() > 0
                                and toggle_button.first.is_visible()
                            ):
                                toggle_button.first.click()
                                new_page.wait_for_timeout(500)
                        except Exception as toggle_error:
                            self.logger.debug(
                                f"Could not click description toggle button: {toggle_error}"
                            )

                        job_page_extractor = PositionInfoExtractor(new_page)

                        try:
                            job_info = job_page_extractor.extract_all_info()
                        finally:
                            try:
                                new_page.close()
                            except Exception as close_error:
                                self.logger.warning(
                                    f"Unable to close job detail page (job {index}): {close_error}"
                                )

                            if main_page and not main_page.is_closed():
                                try:
                                    main_page.bring_to_front()
                                except Exception as bring_error:
                                    self.logger.debug(
                                        f"Failed to bring main page to front: {bring_error}"
                                    )
                                self.bot.browser_operator.set_page(main_page)
                                self.bot.page = main_page

                        if detail_url:
                            job_info["application_url"] = detail_url

                        # Validate extracted data
                        if not job_info.get("job_title") or not job_info.get(
                            "company_name"
                        ):
                            self.logger.warning(
                                f"Job {index}: Missing critical data, skipping"
                            )
                            continue

                        page_processed_count += 1

                        # Queue job for review (filtering happens inside)
                        was_queued = self._queue_job_for_review(job_info)
                        if was_queued:
                            page_queued_count += 1

                        # Small delay between jobs
                        time.sleep(0.3)

                    except Exception as e:
                        self.logger.error(f"Error processing job {index}: {e}")
                        continue

                # Update totals
                total_processed += page_processed_count
                total_queued += page_queued_count

                self.logger.info(
                    f"Page {page_number} completed - Processed: {page_processed_count}, Queued: {page_queued_count}"
                )
                self.send_activity_message(
                    f"Page {page_number} completed: {page_processed_count} jobs processed, {page_queued_count} jobs queued"
                )

                # Try to navigate to next page
                if self._navigate_to_next_page():
                    page_number += 1
                else:
                    # No more pages or stop signal
                    break

            # Final summary
            self.logger.info(
                f"Search completed - Total pages: {page_number}, Total processed: {total_processed}, Total queued: {total_queued}"
            )
            self.send_activity_message(
                f"Search completed: {page_number} pages processed, {total_processed} jobs evaluated, {total_queued} jobs queued"
            )

        except Exception as e:
            self.logger.error(f"Error during job searching steps: {e}")
            raise

    def _navigate_to_next_page(self) -> bool:
        """
        Check for and navigate to next page if available.

        Returns:
            bool: True if navigated to next page, False if no more pages or stop signal
        """
        try:
            pagination_nav = self.bot.page.locator("nav[aria-label='Pagination']")
            if pagination_nav.count() == 0:
                self.logger.info("Pagination navigation not found, assuming last page")
                return False

            next_span = pagination_nav.first.locator("span[aria-label='Next']")
            if next_span.count() == 0:
                self.logger.info(
                    "Next pagination control not found, assuming last page"
                )
                return False

            is_disabled = next_span.first.get_attribute("data-disabled")
            if is_disabled and is_disabled.lower() == "true":
                self.logger.info("Next pagination control disabled, reached last page")
                return False

            if not self.bot.is_running:
                self.logger.info("Stop signal detected, not moving to next page")
                return False

            self.logger.info(
                "Next pagination control available, navigating to next page"
            )
            self.send_activity_message("Moving to next page...")

            self.bot.browser_operator.click_with_op(next_span.first)
            time.sleep(2)  # Wait for page to load
            return True

        except Exception as e:
            self.logger.error(f"Error navigating to next page: {e}")
            return False

    def _scroll_job_cards(self):
        """Scroll the main Dice results page to load all listings."""
        try:
            self.logger.info("Starting to scroll Dice job results page")

            page = self.bot.page
            if page is None:
                self.logger.warning("No active page available for scrolling")
                return

            try:
                page.evaluate("window.scrollTo(0, 0);")
            except Exception as reset_error:
                self.logger.debug(
                    f"Unable to reset page scroll position: {reset_error}"
                )

            iteration = 0
            max_iterations = 40
            scroll_position = 0
            window_height = page.evaluate("() => window.innerHeight || 900")

            while iteration < max_iterations:
                if not self.bot.is_running:
                    self.logger.info("Stop signal detected during page scrolling")
                    break

                scroll_height = page.evaluate(
                    "() => document.documentElement.scrollHeight || document.body.scrollHeight || 0"
                )

                self.logger.debug(
                    f"Page scroll iteration {iteration+1}: position={scroll_position}, "
                    f"height={scroll_height}, viewport={window_height}"
                )

                page.evaluate(
                    "(pos) => { window.scrollTo({ top: pos, behavior: 'auto' }); }",
                    scroll_position,
                )

                time.sleep(random.uniform(0.2, 0.35))

                iteration += 1

                if scroll_height <= window_height:
                    break

                if scroll_position >= scroll_height - window_height:
                    break

                step = int(window_height * 0.8)
                if step <= 0:
                    step = window_height
                scroll_position = min(scroll_position + step, scroll_height)

            self.logger.info(
                f"Page scrolling completed after {iteration} iterations "
                f"(viewport {window_height})"
            )

        except Exception as e:
            self.logger.error(f"Error scrolling job results: {e}")

    def _queue_job_for_review(self, job_data: dict) -> bool:
        """
        Queue individual job with all checks using shared utilities
        Following LinkedIn bot's pattern:
        - Generate consistent IDs
        - Check for duplicates
        - Store job description in shared table
        - Create application history record
        - Run interest matching
        - Run ATS analysis
        - Queue if passes all checks

        Returns:
            bool: True if job was queued, False otherwise
        """
        try:
            # Check if required fields are present
            application_url = job_data.get("application_url", "")
            if not application_url:
                self.logger.info("No application URL, skipping job")
                return False

            # Generate consistent IDs
            job_desc_id = generate_job_description_id(application_url=application_url)
            app_history_id = generate_application_history_id(
                application_url=application_url, user_id=self.bot.user_id
            )

            # Check if this job has already been processed (duplicate detection)
            existing_job = self.application_history_tracker.get_job_item_from_history(
                app_history_id
            )
            if existing_job:
                company = job_data.get("company_name", "Unknown Company")
                title = self._clean_job_title(
                    job_data.get("job_title", "Unknown Position")
                )
                existing_status = existing_job.get("status", "unknown")

                # Only skip if status is NOT in reprocessable states
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
                    # Create application thread with existing status (like LinkedIn bot)
                    self.activity_manager.start_application_thread(
                        company, title, existing_status
                    )
                    msg = f"Skipping {company} | {title} (already processed with status: {existing_status})"
                    self.send_activity_message(msg)
                    self.logger.info(
                        f"Skipping job {company} - {title} - already exists in database with status: {existing_status}"
                    )
                    return False
                else:
                    # Allow reprocessing for these statuses
                    msg = f"Reprocessing {company} | {title} (previous status: {existing_status})"
                    self.send_activity_message(msg)
                    self.logger.info(
                        f"Reprocessing job {company} - {title} - previous status was: {existing_status}"
                    )

            # Standardize post_time using extracted value when available
            from datetime import datetime

            extracted_post_time = job_data.get("post_time")
            post_time = None
            if extracted_post_time:
                try:
                    normalized = extracted_post_time.replace("Z", "+00:00")
                    post_time = datetime.fromisoformat(normalized)
                except Exception as parse_error:
                    self.logger.debug(
                        f"Unable to parse extracted post time '{extracted_post_time}': {parse_error}"
                    )

            if not post_time:
                post_time = datetime.now()

            job_data["post_time"] = post_time.isoformat()

            self.logger.info(
                f"Using post_time {job_data['post_time']} for {job_data.get('company_name', 'Unknown')} | {job_data.get('job_title', 'Unknown')}"
            )

            # Set current job data for maybe_skip_application to use
            self.cur_job_data = job_data

            # Prepare position data with all fields
            position_data = {
                "job_description_id": job_desc_id,
                "application_url": application_url,
                "company_name": job_data.get("company_name", ""),
                "location": job_data.get("location", ""),
                "job_title": job_data.get("job_title", ""),
                "pos_context": job_data.get("pos_context", ""),
                "job_type": job_data.get("job_type", ""),
                "salary_range": job_data.get("salary_range", []),
                "post_time": job_data.get("post_time"),
                "num_applicants": job_data.get("num_applicants", 0),
                "workflow_run_id": self.workflow_run_id,
                "status": ApplicationStatus.STARTED.value,
                "resume_id": (
                    self.config_reader.profile.resume_id if self.config_reader else None
                ),
            }

            # Update application history tracker with all position data (like LinkedIn bot does)
            for attr_name, attr_value in position_data.items():
                self.application_history_tracker.update_application(
                    app_history_id, attr_name, attr_value
                )

            # Set current recording job ID
            self.application_history_tracker.cur_recording_app_history_id = (
                app_history_id
            )

            self.logger.debug(f"Updated application history for job: {app_history_id}")

            # Create application history (stores job_description and application_history)
            try:
                self.application_history_tracker.create_application_history()
            except Exception as create_error:
                # Check if it's a limit exception
                from exceptions import DailyLimitException, SubscriptionLimitException

                if isinstance(
                    create_error, (SubscriptionLimitException, DailyLimitException)
                ):
                    # Propagate limit exceptions to stop hunting
                    raise
                # For other errors, log and continue
                self.logger.error(
                    f"Failed to create application history: {create_error}"
                )
                raise

            self.logger.info(
                f"Created application history and job description for: {job_data.get('job_title')} at {job_data.get('company_name')}"
            )

            # Check if we should skip this application (interest matching + ATS analysis)
            should_skip = self.maybe_skip_application()
            if should_skip:
                self.logger.info(
                    f"Skipping application to {job_data.get('company_name')} - {job_data.get('job_title')}"
                )
                # Status will be set to SKIPPED by maybe_skip_application
                return False

            # If we get here, job passed all checks - queue it
            self.application_history_tracker.update_application(
                app_history_id, "status", ApplicationStatus.QUEUED.value
            )
            self.application_history_tracker.sync_application_history()

            # Update thread status to Queued (thread already created in maybe_skip_application)
            self.activity_manager.update_application_status(
                ApplicationStatus.QUEUED.value
            )

            # Send activity update
            company_name = job_data.get("company_name", "Unknown")
            job_title = self._clean_job_title(job_data.get("job_title", "Unknown"))
            self.logger.info(
                f"Sending queued message with status: {self.activity_manager.current_thread_status}, "
                f"thread: {self.activity_manager.current_thread_title}"
            )
            self.send_activity_message(f"Queued: {company_name} | {job_title}")

            return True

        except Exception as e:
            self.logger.error(f"Error queueing job: {e}")
            # Don't raise - continue processing other jobs
            return False

    def maybe_skip_application(self):
        """
        Check if we should skip this application.
        Identical to v1's maybe_skip_application.
        Returns True if we should skip, False if we should proceed.

        Args:
            ats_score_threshold: ATS score threshold (default 50)
        """
        from services.ai_engine_client import AIEngineClient  # noqa: E402
        from shared.interest_marker import InterestMarker  # noqa: E402
        from shared.interest_marker.defs import JobData  # noqa: E402

        company_name = self.cur_job_data.get("company_name", "Unknown Company")
        job_title = self._clean_job_title(
            self.cur_job_data.get("job_title", "Unknown Position")
        )

        # Check if job was manually removed first (before any other checks)
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

        # Start application thread for this job (starts as "Started")
        self.activity_manager.start_application_thread(
            company_name, job_title, "Started"
        )

        # Send activity message about starting evaluation
        self.send_activity_message(f"Evaluating {company_name} | {job_title}", "action")

        # Read blacklist and job criteria from Supabase
        (
            blacklist_companies_str,
            job_search_criteria,
        ) = self._get_user_filters_from_supabase()

        # Send activity message about checking blacklist
        self.send_activity_message(f"Checking blacklist for {company_name}", "action")

        # check if the company is in the blacklist
        self.logger.info(
            f"Checking if company {self.cur_job_data['company_name']} is a good match"
        )

        def is_in_blacklist(company_name) -> tuple[bool, str]:
            system = f"""
            You have a blacklist of companies that you do not want to apply to.
            Blacklist: {blacklist_companies_str}
            """
            # Simple string check first
            if company_name.lower() in blacklist_companies_str.lower():
                return True, "Company is in the blacklist"

            prompt = f"Is this company in the blacklist? {company_name}"
            format = {
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
            response = ai_client.call_ai(prompt=prompt, system=system, format=format)

            # Handle case where AI client returns None due to auth errors
            if response is None:
                self.logger.warning(
                    "AI engine returned None, defaulting to not blacklisted"
                )
                msg = "AI engine unavailable, defaulting to not blacklisted"
                return False, msg

            is_in_blacklist_bool = response.get("answer", False)
            thinking = response.get("thinking", "")
            if thinking and is_in_blacklist_bool:
                self.logger.info(f"AI Thinking: {thinking}")
            self.logger.info(f"is_in_blacklist: {is_in_blacklist_bool}")
            return is_in_blacklist_bool, thinking

        def is_a_good_match(job_data):
            """
            Check if the job is a good match based on job matching criteria.
            Even if the resume is not a good match, the job is still a good
            match if the job matching criteria is met.
            """
            interest_marker = InterestMarker(
                job_data,
                job_search_criteria,
                display_thinking_callback=self.maybe_display_activity,
            )
            # In V1 this would use execute_callback, in V2 we'll log
            company = self.cur_job_data.get("company_name", "")
            title = self.cur_job_data.get("job_title", "")
            self.logger.info(
                f"Checking if {company} - {title} matches what you are " f"looking for"
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
            # TODO: Remove this once we have a proper interest marker
            should_skip = False

            if not should_skip:
                # Add criteria alignment to application history
                # (like v1 adds to submission queue)
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
            formatted_alignments = interest_marker.format_alignments(alignments)
            msg = f"The position matches your criteria. " f"Applying to {company_title}"
            if should_skip:
                msg = f"Skipping {company_title} due to not a good match"
            if formatted_alignments:
                msg += f"\n\n{formatted_alignments}"
            # In V1 this would use execute_callback, in V2 we'll log
            self.logger.info(msg)
            return should_skip, reasoning

        # Check if company is a staffing company (before blacklist check)
        def _is_existing_staffing_company(
            company_name: str,
        ) -> tuple[bool, str]:
            """
            Check if company is in the known staffing companies list
            (fast lookup).
            """
            if not self.config_reader.filters.skip_staffing_companies:
                return False, "Staffing company check is disabled"

            if not self.config_reader.filters.staffing_companies:
                return False, "No staffing companies list loaded"

            company_name_lower = company_name.lower()
            staffing_list = self.config_reader.filters.staffing_companies
            if company_name_lower in staffing_list:
                return True, f"{company_name} is a known staffing company"

            msg = f"{company_name} is not in the staffing companies list"
            return False, msg

        # First, check if company is in existing staffing companies list
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
            # Found in existing list - skip immediately
            if thinking:
                self.send_activity_message(f"Analysis: {thinking}", "thinking")

            skip_reason = (
                f"Skipping {company_name} | {job_title} (known staffing company)"
            )
            self.send_activity_message(skip_reason, "result")

            # Update thread status to Skipped (thread already created at line 749)
            self.activity_manager.update_application_status(
                ApplicationStatus.SKIPPED.value
            )
            return True

        # Not in existing list - use AI to check and collect new staffing companies
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

                # Update thread status to Skipped (thread already created at line 749)
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

        # Send activity message about blacklist result
        if in_blacklist:
            # Show AI thinking if available
            if thinking:
                self.send_activity_message(f"AI Analysis: {thinking}", "thinking")

            # Send activity message about blacklist skip
            skip_reason = f"Skipping {company_name} | company is blacklisted"
            self.send_activity_message(skip_reason, "result")
            # Update thread status to Skipped
            self.activity_manager.update_application_status(
                ApplicationStatus.SKIPPED.value
            )
            return True
        else:
            # Show that company passed blacklist check
            msg = f"{company_name} not found in blacklist - proceeding"
            self.send_activity_message(msg, "result")
            # Send activity message about checking job criteria match
            msg = f"Checking job criteria match for {company_name}"
            self.send_activity_message(msg, "action")

            job_data: JobData = JobData(
                job_title=self.cur_job_data.get("job_title", ""),
                job_description=self.cur_job_data.get("pos_context", ""),
                company_name=self.cur_job_data.get("company_name", ""),
                post_time=self.cur_job_data.get("post_time", ""),
                location=self.cur_job_data.get("location", ""),
            )
            try:
                should_skip, think = is_a_good_match(job_data)
                matched = not should_skip
            except Exception as e:
                self.logger.warning(f"Job matching failed: {e}, defaulting to apply")
                should_skip, think = (
                    False,
                    "Job matching unavailable, defaulting to apply",
                )
                matched = True

            if not matched:
                # Show AI thinking process if available
                if think:
                    self.send_activity_message(f"AI Analysis: {think}", "thinking")

                # Send activity message about criteria mismatch
                msg = f"Skipping {company_name} | doesn't match job criteria"
                self.send_activity_message(msg, "result")

                log_msg = (
                    f"Skipping application because it's not a good match: "
                    f"{self.cur_job_data['company_name']}"
                )
                self.logger.info(log_msg)
                skip_reason = "Not a good match"
                if think:
                    skip_reason = f"Not a good match - {think}"
                    self.logger.debug(f"Skip reason: {skip_reason}")
                # Update thread status to Skipped
                self.activity_manager.update_application_status(
                    ApplicationStatus.SKIPPED.value
                )
                # In V1 this would update application_history_tracker
                # and send mixpanel events - Skipping for V2 as requested
                return True
            if matched:
                # Show AI thinking process if available
                if think:
                    self.send_activity_message(f"AI Analysis: {think}", "thinking")

                # Send activity message about successful match
                msg = (
                    f"{company_name} matches job criteria - "
                    f"proceeding to ATS analysis"
                )
                self.send_activity_message(msg, "result")
                self.analyze_ats_score(job_data)
        return False

    def maybe_display_activity(self, text: str):
        """Display activity callback for AI thinking"""
        # Send AI thinking process to activity log
        self.send_activity_message(f"AI Thinking: {text}", "thinking")

    def analyze_ats_score(self, job_data):
        """
        Analyze ATS score - identical to v1's analyze_ats_score functionality
        """
        from shared.ats_marker import ATSMarker  # noqa: E402
        from shared.ats_marker.defs import ApplicantData  # noqa: E402

        # Use real resume data from config reader
        # Use additional experience from ATS template (loaded from database)
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

        # Get JWT token for ATS analysis
        from constants import SERVICE_GATEWAY_URL  # noqa: E402
        from services.jwt_token_manager import jwt_token_manager  # noqa: E402

        user_token = jwt_token_manager.get_token()
        if not user_token:
            self.logger.warning("No JWT token available for ATS analysis")

        # Create ATS marker instance
        ats_marker = ATSMarker(
            job_data=job_data,
            applicant_data=applicant_data,
            bot=self,
            display_thinking_callback=self.maybe_display_activity,
            alignment_score_threshold=0.8,
            service_gateway_url=SERVICE_GATEWAY_URL,
            user_token=user_token,
        )

        # Send activity message about starting ATS analysis
        company_name = job_data.company_name
        msg = f"Running ATS analysis for {company_name}"
        self.send_activity_message(msg, "action")

        self.logger.info(
            f"Analyzing ATS score for {job_data.company_name} - "
            f"{job_data.job_title}"
        )

        # Run the ATS analysis
        try:
            score, alignments, keywords_to_add = ats_marker.run()

            # Store ATS analysis results in cur_job_data for later resume generation
            self.cur_job_data["initial_ats_score"] = score
            self.cur_job_data["initial_ats_alignments"] = [
                alignment.to_dict() for alignment in alignments
            ]
            self.cur_job_data["keywords_to_add"] = keywords_to_add

            # Calculate missing requirements (alignment score < 80% of max score)
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

            # Update application history with ATS data (like v1 does)
            if self.application_history_tracker.cur_recording_app_history_id:
                self.application_history_tracker.update_application(
                    self.application_history_tracker.cur_recording_app_history_id,
                    "ats_score",
                    score,
                )
                self.application_history_tracker.update_application(
                    self.application_history_tracker.cur_recording_app_history_id,
                    "ats_alignments",
                    [alignment.to_dict() for alignment in alignments],
                )
                self.application_history_tracker.update_application(
                    self.application_history_tracker.cur_recording_app_history_id,
                    "ats_keyword_to_add_to_resume",
                    keywords_to_add,
                )
                # Sync to database after updating ATS data
                self.application_history_tracker.sync_application_history()

            # Show ATS analysis thinking process first
            formatted_results = ats_marker.format_alignments(score, alignments)
            if formatted_results:
                # Show full ATS analysis with markdown table formatting
                self.send_activity_message(
                    f"{formatted_results}",
                    "thinking",
                )

            # Send activity message with ATS score results
            if score >= 70:  # Good score threshold
                score_msg = f"ATS Score: {score}/100 - Strong resume match!"
                self.send_activity_message(score_msg, "result")
                log_msg = (
                    f"Good ATS score: {score}/100 - "
                    f"Resume aligns well with job requirements"
                )
                self.logger.info(log_msg)
            elif score >= 50:  # Moderate score
                score_msg = f"ATS Score: {score}/100 - Moderate match"
                self.send_activity_message(score_msg, "result")
                self.logger.info(
                    f"Moderate ATS score: {score}/100 - Some improvements possible"
                )
            else:  # Low score
                score_msg = f"ATS Score: {score}/100 - Weak resume match"
                self.send_activity_message(score_msg, "result")
                self.logger.info(
                    f"Low ATS score: {score}/100 - Significant gaps in requirements"
                )

            # Format and log the results like V1 does
            formatted_results = ats_marker.format_alignments(score, alignments)
            self.logger.info(f"ATS Analysis Results:\n{formatted_results}")

            if keywords_to_add:
                suggestions = ", ".join(keywords_to_add[:3])
                ellipsis = "..." if len(keywords_to_add) > 3 else ""
                self.send_activity_message(
                    f"ATS Keywords Suggestions: {suggestions}{ellipsis}", "result"
                )
                keywords_str = ", ".join(keywords_to_add)
                log_msg = f"Suggested keywords to improve ATS score: " f"{keywords_str}"
                self.logger.info(log_msg)

            # Generate ATS-optimized resume if enabled and template available
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
        For Dice bot, we only check against the existing staffing company list.
        We don't use AI to detect new staffing companies (that's done by LinkedIn bot).

        This method is called by maybe_skip_application() after the existing list check,
        but for Dice we simply return False since we rely only on the known list.

        Returns:
            False - Dice bot doesn't do AI-based staffing company detection
        """
        # For Dice, we only use the existing staffing company list
        # AI detection of new staffing companies is handled by LinkedIn bot only
        self.logger.debug(
            "Dice bot skipping AI staffing company check - using known list only"
        )
        return False

    def _generate_ats_optimized_resume(self) -> Optional[str]:
        """
        Generate ATS-optimized resume for Dice job application

        Returns:
            Path to generated optimized resume PDF, or None if generation failed
        """
        try:
            import tempfile
            from pathlib import Path

            import requests

            from constants import SERVICE_GATEWAY_URL
            from services.jwt_token_manager import jwt_token_manager

            # Get job description from cur_job_data
            job_description = self.cur_job_data.get("pos_context", "")
            if not job_description:
                msg = "No job description available for ATS optimization"
                logger.warning(msg)
                return None

            # Get additional skills from ATS template
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

            # Get JWT token for API calls
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

            # Step 1: Use stored ATS analysis from cur_job_data
            initial_ats_score = self.cur_job_data.get("initial_ats_score", 0)
            initial_ats_alignments = self.cur_job_data.get("initial_ats_alignments", [])
            keywords_to_add = self.cur_job_data.get("keywords_to_add", [])
            missing_requirements = self.cur_job_data.get("missing_requirements", [])

            msg = f"Initial ATS Score: {initial_ats_score}/100"
            self.send_activity_message(msg, "result")

            # Step 2: Check which missing requirements can be addressed
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

            # Step 3: Generate optimized resume
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

            # Step 4: Analyze final ATS score with optimized resume
            self.send_activity_message("Validating improvements...", "action")

            from bs4 import BeautifulSoup

            from shared.ats_marker import ATSMarker
            from shared.ats_marker.defs import ApplicantData, JobData

            # Extract text from optimized HTML
            soup = BeautifulSoup(optimized_html, "html.parser")
            optimized_resume_text = soup.get_text()

            # Create data objects for final analysis
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

            # Run final ATS analysis
            final_ats_marker = ATSMarker(
                final_job_data,
                final_applicant_data,
                user_token=token,
            )

            try:
                final_ats_score, final_alignments_objects, _ = final_ats_marker.run()

                # Convert Alignment objects to dict format
                final_ats_alignments = []
                for alignment in final_alignments_objects:
                    final_ats_alignments.append(
                        {
                            "requirement": alignment.requirement.description,
                            "alignment_score": alignment.alignment_score,
                            "reason": alignment.reason,
                        }
                    )

                # Calculate improvement
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

            # Step 5: Store all results in application history
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
                    "ats_template_id": template_id,  # Store template ID for original HTML lookup
                }

                for field, value in updates.items():
                    self.application_history_tracker.update_application(
                        app_id, field, value
                    )

                self.application_history_tracker.sync_application_history()
                logger.info(
                    f"Stored complete ATS analysis in application history: {app_id}"
                )

            # Step 6: Convert optimized HTML to PDF
            self.send_activity_message(
                "Converting optimized resume to PDF...", "action"
            )

            from util.pdf_generator import generate_pdf_from_html

            # Create temporary directory for the optimized resume PDF
            temp_dir = Path(tempfile.mkdtemp())
            company_name = (
                self.cur_job_data.get("company_name", "").replace(" ", "_").lower()
            )
            job_title = self.cur_job_data.get("job_title", "").replace(" ", "_").lower()
            pdf_filename = f"optimized_resume_{company_name}_{job_title}"

            # Generate PDF from optimized HTML
            try:
                optimized_pdf_path = generate_pdf_from_html(
                    html_content=optimized_html,
                    output_dir=temp_dir,
                    filename=pdf_filename,
                )

                if optimized_pdf_path and optimized_pdf_path.exists():
                    logger.info(f"Generated optimized resume PDF: {optimized_pdf_path}")

                    # Upload PDF to blob storage
                    self.send_activity_message(
                        "Uploading optimized resume to cloud storage...", "action"
                    )

                    try:
                        blob_url = self._upload_pdf_to_blob_storage(
                            optimized_pdf_path, ats_resume_id
                        )

                        if blob_url:
                            logger.info(f"Uploaded PDF to blob storage: {blob_url}")

                            # Update ATS resume record with blob_url
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
        """Upload generated PDF to blob storage via service gateway"""
        try:
            import requests

            from constants import SERVICE_GATEWAY_URL
            from services.jwt_token_manager import jwt_token_manager

            token = jwt_token_manager.get_token()
            if not token:
                logger.warning("No JWT token for blob upload")
                return ""

            # Read PDF file
            with open(pdf_path, "rb") as f:
                pdf_content = f.read()

            # Upload via service gateway
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
            else:
                logger.error(f"Upload failed: {response.status_code} - {response.text}")
                return ""

        except Exception as e:
            logger.error(f"Error uploading PDF: {e}")
            return ""

    def _update_ats_resume_blob_url(self, ats_resume_id: str, blob_url: str) -> bool:
        """Update ATS resume record with blob URL"""
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
