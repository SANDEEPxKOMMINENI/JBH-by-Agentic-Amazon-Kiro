#!/usr/bin/env python3
"""
Start Searching Action for Indeed Bot
"""

import logging
import os
import random
import re
import sys
import time
import traceback
from typing import Any, Dict, Optional

import requests

# Add parent directories to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from browser.browser_operator import BrowserOperator
from constants import IS_WINDOWS, SERVICE_GATEWAY_URL
from indeed_bot.actions.base_action import BaseAction
from shared.models.application_history import ApplicationStatus
from util.application_history_id_generator import (
    generate_application_history_id,
    generate_job_description_id,
)

logger = logging.getLogger(__name__)


class StartSearchingAction(BaseAction):
    """Action to start the Indeed job searching and queueing process"""

    def __init__(self, bot_instance):
        super().__init__(bot_instance)
        self.workflow_run_id = bot_instance.workflow_run_id
        self.cur_job_data = {}  # Current job data for maybe_skip_application

        # Will be initialized after browser operator is ready
        self.config_reader = None
        self.application_history_tracker = None

        # Store date_posted filter for calculating post_time
        self.date_posted_days = None

        persist_env_value = os.getenv("INDEED_PERSIST_SESSION", "true").lower()
        self.persist_browser_state = persist_env_value in {"1", "true", "yes", "on"}

    @property
    def action_name(self) -> str:
        return "start_searching"

    def _clean_job_title(self, job_title: str) -> str:
        """Remove unwanted suffixes from job titles like '- job post'"""
        if not job_title:
            return job_title
        # Remove common Indeed job post suffixes
        suffixes_to_remove = [" - job post", "- job post", " -job post", "-job post"]
        cleaned = job_title
        for suffix in suffixes_to_remove:
            if cleaned.endswith(suffix):
                cleaned = cleaned[: -len(suffix)].strip()
        return cleaned

    def _save_browser_state(self, reason: str):
        """No-op in CDP mode; Chrome profile persists automatically."""
        self.logger.debug(
            "Skipping browser state save (%s) because Chrome profile persists automatically",
            reason,
        )

    def _disable_link_navigation(self, job_card):
        """
        Disable the <a> tag inside the job card to prevent navigation (Windows only).
        This prevents the link from navigating when clicked.
        """
        if not IS_WINDOWS:
            return

        try:
            disable_script = """
            (el) => {
                const link = el.querySelector('a.jcs-JobTitle, a[role="button"]');
                if (link) {
                    // Remove href attribute to prevent navigation
                    link.removeAttribute('href');
                    // Prevent click events from causing navigation
                    link.onclick = (e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        return false;
                    };
                }
            }
            """
            # Use the locator's evaluate method directly
            job_card.evaluate(disable_script)
        except Exception as e:
            self.logger.debug(f"Could not disable link navigation: {e}")

    def execute(self) -> Dict[str, Any]:
        """
        Start the Indeed searching process
        Returns status dict with success/error info
        """
        try:
            self.logger.info(f"Starting Indeed bot {self.bot.bot_id}")

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

            # Navigate to Indeed homepage
            self.bot.current_url = self._navigate_to_indeed_sync()
            self.send_activity_message("Opened Indeed homepage")

            # Check if sign-in is required and handle login
            login_success, login_error = self._check_and_handle_login()
            if not login_success:
                return {
                    "success": False,
                    "message": f"Failed to login: {login_error}",
                    "status": "error",
                }

            # Generate search URL with AI and navigate to it
            time.sleep(5)
            built_url = self._build_indeed_url_from_db_config()
            if built_url:
                self.send_activity_message(f"Opening Indeed search page: `{built_url}`")
                self.bot.current_url = self.bot.browser_operator.navigate_to(built_url)
                time.sleep(3)  # Wait for search results to load
            else:
                self.logger.error("Failed to build Indeed URL from config")
                return {
                    "success": False,
                    "message": "Failed to build Indeed URL from config",
                    "status": "error",
                }

            self.send_status_update(
                "running", "Successfully launched and navigated to Indeed"
            )

            # Perform job searching steps
            time.sleep(5)
            self._perform_job_searching_steps()

            # After completing the search, automatically stop the bot
            self.logger.info(
                f"Indeed bot {self.bot.bot_id} completed job searching batch"
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
                "message": "Indeed bot completed job searching batch successfully",
                "status": "completed",
                "current_url": self.bot.current_url,
            }

        except Exception as e:
            self.logger.error(f"Failed to start Indeed bot in execute: {e}")

            traceback.print_exc()

            # Cleanup on error
            self._cleanup_on_error()

            self.send_status_update("error", f"Failed to start: {str(e)}")

            return {
                "success": False,
                "message": f"Failed to start Indeed bot in execute: {str(e)}",
                "status": "error",
            }

    def _init_browser_sync(self):
        """
        Initialize browser with bundled Chromium (sync version)

        Set INDEED_PERSIST_SESSION=false to force fresh sessions if detection
        issues resurface; otherwise Chrome's own profile will persist sessions.
        """
        try:
            if self.persist_browser_state:
                self.logger.info(
                    "Initializing browser operator with persisted session support"
                )
            else:
                self.logger.info(
                    "Initializing browser operator with fresh session (no saved state)"
                )

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

            # Create browser operator with persisted or fresh session based on flag
            self.bot.browser_operator = BrowserOperator(
                headless=headless_on,
            )

            # Set bot instance reference for stop signal detection
            self.bot.browser_operator.set_bot_instance(self.bot)

            # Set callbacks for status and activity updates
            self.bot.browser_operator.set_callbacks(
                status_callback=lambda status, message: self.send_status_update(
                    status, message
                ),
                activity_callback=lambda message: self.send_activity_message(message),
            )

            # Start browser (creates and returns page)
            self.bot.page = self.bot.browser_operator.start()

            if self.persist_browser_state:
                self.logger.info(
                    "Browser started; persisted state will load when available"
                )
            else:
                self.logger.info(
                    "Browser started with fresh session (no cookies loaded)"
                )

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

    def _navigate_to_indeed_sync(self) -> str:
        """
        Navigate to Indeed with warmup strategy
        1. Go to homepage first (less strict, avoids 403)
        2. Scroll and interact naturally
        3. Then proceed to jobs page
        """
        try:
            self.logger.info("Session warmed up, navigating to jobs page...")
            jobs_url = "https://www.indeed.com/jobs"
            current_url = self.bot.browser_operator.navigate_to(jobs_url)
            time.sleep(2)  # Wait for page to stabilize

            return current_url
        except Exception as e:
            self.logger.error(f"Failed to navigate to Indeed: {e}")
            raise

    def _check_and_handle_login(self) -> tuple[bool, str]:
        """
        Check if sign-in is required and handle login flow
        Returns (success, error_message)
        """
        try:
            # Check if sign-in button is present
            sign_in_button = self.bot.page.locator(
                "div[data-gnav-element-name*='SignIn']"
            )

            if sign_in_button.count() > 0 and not self._is_logged_in():
                # Sign-in button is present and user is not logged in - click it
                self.send_activity_message("Sign-in required - opening sign-in page")
                self.bot.browser_operator.click_with_op(sign_in_button.first)
                time.sleep(2)  # Wait for sign-in page to load

                # Wait for user to complete login
                login_success, login_error = self.login_and_save_state()

                if not login_success:
                    # Login failed or timed out
                    self.send_activity_message(f"Login failed: {login_error}")
                    return False, login_error

                # Once logged in, navigate to Indeed homepage again
                self.send_activity_message(
                    "Login successful - navigating back to Indeed"
                )
                self.bot.current_url = self._navigate_to_indeed_sync()
                self.send_activity_message("Returned to Indeed homepage")
                return True, ""

            elif self._is_logged_in():
                self.send_activity_message("Already logged in to Indeed")
                self._save_browser_state("already logged in")
                return True, ""

            # No sign-in button found and not logged in - proceed anyway
            self.send_activity_message("No sign-in required")
            return True, ""

        except Exception as e:
            self.logger.error(f"Error during login check: {e}")
            return False, f"Login check error: {str(e)}"

    def _build_indeed_url_from_db_config(self) -> Optional[str]:
        """Build Indeed search URL from workflow run config in database

        Retrieves configuration from ConfigReader (loaded from database)
        and calls service-gateway to build the Indeed search URL.

        Returns:
            Built Indeed URL or None if build failed
        """
        if not self.config_reader:
            self.logger.info("ConfigReader not initialized, cannot build Indeed URL")
            return None

        # Get workflow run configuration from database
        bot_config = self.config_reader.workflow_run_config
        if not bot_config:
            self.logger.info("No workflow run config in database, cannot build URL")
            return None

        try:
            from services.jwt_token_manager import jwt_token_manager

            # Get JWT token for authentication
            token = jwt_token_manager.get_token()
            headers = {"Content-Type": "application/json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            else:
                self.logger.warning("No JWT token available for Indeed URL building")

            # Call service-gateway endpoint to build URL
            response = requests.post(
                f"{SERVICE_GATEWAY_URL}/api/infinite-runs/generate-platform-url",
                json={"platform": "indeed", "bot_config": bot_config},
                headers=headers,
                timeout=10,
            )

            if response.status_code == 200:
                result = response.json()
                if result.get("success") and result.get("url"):
                    built_url = result["url"]
                    self.logger.info(f"Successfully built Indeed URL: {built_url}")
                    return built_url
                else:
                    error_msg = result.get("error", "Unknown error")
                    self.logger.error(f"Failed to build Indeed URL: {error_msg}")
                    return None
            else:
                self.logger.error(
                    f"Service-gateway returned error "
                    f"{response.status_code}: {response.text}"
                )
                return None

        except Exception as e:
            self.logger.error(f"Exception while building Indeed URL: {e}")
            return None

    def _fill_search_form(self):
        """Fill in the Indeed search form with job title and location from config"""
        try:
            self.send_activity_message("Filling in search criteria...")

            # Get job title and location from config filters
            job_title = self.config_reader.filters.job_description or ""
            location = self.config_reader.filters.location or ""

            if not job_title:
                self.logger.warning(
                    f"Missing search criteria - job_title: '{job_title}'"
                )
                self.send_activity_message("Warning: Missing job title in config")
                return

            # Fill in job title input
            job_title_input = self.bot.page.locator("input#text-input-what")
            if job_title_input.count() > 0:
                job_title_input = job_title_input.first
                if job_title_input.is_visible():
                    # fill_with_op automatically clears first
                    self.bot.browser_operator.fill_with_op(job_title_input, job_title)
                    self.send_activity_message(f"Job title set to: {job_title}")
                    self.logger.info(f"Filled job title: {job_title}")
                else:
                    self.logger.warning("Job title input not visible")
            else:
                self.logger.warning("Job title input not found")

            # Fill in location input
            location_input = self.bot.page.locator("input#text-input-where")
            if location_input.count() > 0:
                location_input = location_input.first
                if location_input.is_visible():
                    # fill_with_op automatically clears first
                    self.bot.browser_operator.fill_with_op(location_input, location)
                    self.send_activity_message(f"Location set to: {location}")
                    self.logger.info(f"Filled location: {location}")
                else:
                    self.logger.warning("Location input not visible")
            else:
                self.logger.warning("Location input not found")

            # Click the search button
            search_button = self.bot.page.locator('button[type="submit"]')
            if search_button.count() > 0:
                search_button = search_button.first
                if search_button.is_visible():
                    self.bot.browser_operator.click_with_op(search_button)
                    self.send_activity_message("Started job search")
                    time.sleep(3)  # Wait for search results to load
                    self.logger.info("Clicked search button")
                else:
                    self.logger.warning("Search button not visible")
            else:
                self.logger.warning("Search button not found")

        except Exception as e:
            self.logger.error(f"Failed to fill search form: {e}")
            self.send_activity_message(f"Error filling search form: {str(e)}")

    def _apply_date_posted_filter_via_url(self):
        """Apply date posted filter by modifying the URL with fromage parameter

        This method ensures backward compatibility with existing Indeed workflow runs
        that were created before the date_posted filter was added.
        """
        try:
            # Get date_posted from platform_filters
            platform_filters = self.config_reader.get_platform_filters()
            if not platform_filters or "indeed" not in platform_filters:
                self.logger.warning(
                    "No Indeed platform filters found in workflow_run, using default (24 hours)"
                )
                self.logger.info(
                    "This may be an old workflow run created before date_posted filter was added"
                )
                date_posted = "1"  # Default to 24 hours
            else:
                indeed_filters = platform_filters.get("indeed", {})
                date_posted = indeed_filters.get("date_posted")

                # Check if date_posted is missing or empty in the indeed filters
                if not date_posted:
                    self.logger.warning(
                        "date_posted is missing or empty in platform_filters.indeed, using default (24 hours)"
                    )
                    date_posted = "1"
                else:
                    self.logger.info(
                        f"Found date_posted filter in platform_filters: {date_posted}"
                    )

            # Final sanity check - should never be empty at this point
            if not date_posted:
                self.logger.error(
                    "date_posted is still empty after all checks, forcing default (24 hours)"
                )
                date_posted = "1"  # Ensure we always have a default

            # Store date_posted for calculating post_time later
            self.date_posted_days = int(date_posted)

            # Map our date_posted values to Indeed's fromage parameter
            # fromage=X means "jobs posted within X days"
            # "1" (24 hours) -> fromage=1
            # "3" (3 days) -> fromage=3
            # "7" (7 days) -> fromage=7
            # "14" (14 days) -> fromage=14

            self.logger.info(
                f"Applying date posted filter via URL: last {date_posted} days"
            )
            self.send_activity_message(
                f"Applying date filter: Last {date_posted} day(s)"
            )

            # Get current URL
            current_url = self.bot.page.url
            self.logger.info(f"Current URL: {current_url}")

            # Add or update the fromage parameter
            if "?" in current_url:
                # URL already has parameters
                if "fromage=" in current_url:
                    # Replace existing fromage parameter
                    new_url = re.sub(
                        r"fromage=\d+", f"fromage={date_posted}", current_url
                    )
                else:
                    # Add fromage parameter
                    new_url = f"{current_url}&fromage={date_posted}"
            else:
                # No parameters yet, add fromage as first parameter
                new_url = f"{current_url}?fromage={date_posted}"

            self.logger.info(f"Navigating to URL with date filter: {new_url}")

            # Navigate to the modified URL
            self.bot.browser_operator.navigate_to(new_url)
            time.sleep(2)  # Wait for page to reload with filter applied

            self.logger.info(f"Applied date filter: last {date_posted} day(s)")
            self.send_activity_message(
                f"Date filter applied: Last {date_posted} day(s)"
            )

        except Exception as e:
            self.logger.error(f"Failed to apply date posted filter via URL: {e}")
            # Don't raise - continue with search even if filter fails

    def login_and_save_state(self) -> tuple[bool, str]:
        """
        Handle login and save state
        Returns (success, error_message)
        """
        try:
            self.send_activity_message("Checking login status...")

            # Check if already logged in
            if self._is_logged_in():
                self.send_activity_message("Already logged in to Indeed")

                self._save_browser_state("login check already logged in")

                return True, ""

            # Need to login
            self.send_activity_message("Please login to Indeed in the browser window")
            self.send_activity_message("Waiting for login (timeout: 2 minutes)...")

            # Wait for login (poll for login status)
            login_timeout = 120  # 2 minutes
            start_time = time.time()

            while time.time() - start_time < login_timeout:
                if not self.bot.is_running:
                    return False, "Bot stopped while waiting for login"

                if self._is_logged_in():
                    self.send_activity_message("Login successful!")

                    self._save_browser_state("post-login success")

                    return True, ""

                time.sleep(2)  # Check every 2 seconds

            # Timeout
            return False, "Login timeout - please try again"

        except Exception as e:
            self.logger.error(f"Login error: {e}")
            return False, f"Login error: {str(e)}"

    def _is_logged_in(self) -> bool:
        """Check if user is logged in to Indeed"""
        try:
            # Check for Indeed account menu button (indicates logged in)
            account_menu = self.bot.page.locator("button#AccountMenu")

            # Check if button exists and is visible
            if account_menu.count() > 0:
                try:
                    return account_menu.first.is_visible()
                except:
                    return False

            return False

        except Exception as e:
            self.logger.error(f"Error checking login status: {e}")
            return False

    def _perform_job_searching_steps(self):
        """Main job searching loop - process jobs across all pages"""
        try:
            self.send_activity_message("Starting job search and queue process...")

            # Import the position info extractor
            from indeed_bot.position_info_extractor import PositionInfoExtractor

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

                # Step 1: Get job cards container
                job_cards_container = self.bot.page.locator(
                    "div#mosaic-provider-jobcards"
                )
                if job_cards_container.count() == 0:
                    self.logger.warning("Job cards container not found")
                    self.send_activity_message("No job results found")
                    break

                self.logger.info("Found job cards container")

                # Step 2: Get initial job cards
                job_cards_locator = job_cards_container.first.locator(
                    "div[class*=slider_item]"
                )
                initial_count = job_cards_locator.count()
                self.logger.info(f"Initial job cards count: {initial_count}")

                if initial_count == 0:
                    self.logger.warning("No job cards found")
                    self.send_activity_message("No job listings found on this page")
                    break

                # Step 3: Click on first job card to ensure scroll area is visible
                self.send_activity_message(
                    f"Found {initial_count} initial job listings"
                )

                # Step 4: Scroll through job cards to load all results
                self._scroll_job_cards(job_cards_container.first)

                # Step 5: Re-collect all job cards after scrolling
                all_job_cards = [j for j in job_cards_locator.all() if j.is_visible()]
                total_count = len(all_job_cards)
                self.logger.info(f"Total job cards after scrolling: {total_count}")
                self.send_activity_message(
                    f"Loaded {total_count} job listings, processing..."
                )

                # Step 6: Process each job card
                position_extractor = PositionInfoExtractor(self.bot.page)
                page_processed_count = 0
                page_queued_count = 0

                for index, job_card in enumerate(all_job_cards, 1):
                    try:
                        # Check stop signal
                        if not self.bot.is_running:
                            self.logger.info(
                                "Stop signal detected, halting job processing"
                            )
                            break

                        self.logger.info(f"Processing job {index}/{total_count}")

                        # On Windows, disable link navigation before clicking
                        if IS_WINDOWS:
                            self._disable_link_navigation(job_card)

                        # Click on job card to load details on the right side using mouse
                        self.bot.browser_operator.click_with_op(job_card)
                        time.sleep(0.5)  # Wait for job details to load

                        # Extract job information using position extractor
                        job_info = position_extractor.extract_all_info()

                        # Validate extracted data
                        if not job_info.get("job_title") or not job_info.get(
                            "company_name"
                        ):
                            self.logger.warning(
                                f"Job {index}: Missing critical data, skipping"
                            )
                            continue

                        page_processed_count += 1

                        # Check stop signal before queueing (AI analysis happens here)
                        if not self.bot.is_running:
                            self.logger.info("Stop signal detected before queueing job")
                            break

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
        # Check for next page button
        next_page_button = self.bot.page.locator(
            "a[data-testid*='pagination-page-next']"
        )

        if next_page_button.count() > 0 and next_page_button.first.is_visible():
            # Check stop signal before moving to next page
            if not self.bot.is_running:
                self.logger.info("Stop signal detected, not moving to next page")
                return False

            self.logger.info("Next page button found, navigating to next page")
            self.send_activity_message("Moving to next page...")

            # Click next page button
            self.bot.browser_operator.click_with_op(next_page_button.first)
            time.sleep(2)  # Wait for page to load

            return True
        else:
            self.logger.info("No next page button found, search completed")
            return False

    def _scroll_job_cards(self, scroll_container):
        """Scroll through job cards container to load all results - matching LinkedIn bot's approach"""
        try:
            self.logger.info("Starting to scroll job cards")

            # Get scroll area height
            scroll_height = scroll_container.evaluate("el => el.scrollHeight")

            self.logger.info(f"Scroll area - Total height: {scroll_height}")

            # Calculate scroll steps using LinkedIn's approach
            delta_y = 800  # Scroll amount per step (matching LinkedIn)
            scroll_steps = int(scroll_height // delta_y + 1)

            self.logger.info(f"Will scroll {scroll_steps} times to load all listings")

            # Scroll down slowly like LinkedIn bot does
            for i in range(scroll_steps):
                scroll_amount = scroll_height / scroll_steps
                self.logger.debug(
                    f"Scroll step {i+1}/{scroll_steps}, amount: {scroll_amount:.1f}px"
                )

                # Use browser operator's mouse wheel scrolling (natural scrolling)
                # This simulates real mouse wheel events, not JavaScript manipulation
                self.bot.browser_operator.scroll_with_op(
                    delta_x=0, delta_y=int(scroll_amount)
                )

                # Random delay like LinkedIn bot (0.1-0.3 seconds)
                delay = random.randint(1, 3) / 10
                time.sleep(delay)

                # Update scroll height in case content loaded
                try:
                    scroll_height = scroll_container.evaluate("el => el.scrollHeight")
                except Exception:
                    pass  # Continue even if we can't update height

            self.logger.info(f"Scrolling completed after {scroll_steps} scrolls")

        except Exception as e:
            self.logger.error(f"Error scrolling job cards: {e}")

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

            # Calculate post_time based on date_posted filter
            # If date_posted_days is set, calculate post_time as (today - filter days)
            # Otherwise, set it as today
            from datetime import datetime, timedelta

            if self.date_posted_days is not None and self.date_posted_days > 0:
                # Jobs are posted within the last N days, so estimate as (today - N/2 days)
                # This gives a reasonable estimate for "within last N days"
                estimated_days_ago = (
                    self.date_posted_days // 2 if self.date_posted_days > 1 else 0
                )
                post_time = datetime.now() - timedelta(days=estimated_days_ago)
            else:
                # No filter applied, assume posted today
                post_time = datetime.now()

            self.logger.info(
                f"Calculated post_time: {post_time.isoformat()} (filter: {self.date_posted_days} days)"
            )

            # Update job_data with calculated post_time for maybe_skip_application
            job_data["post_time"] = post_time.isoformat()

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
                "salary_range": job_data.get("salary_range", ""),
                "post_time": post_time.isoformat(),  # Store as ISO format string
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
        # Check stop signal at start of maybe_skip_application
        if not self.bot.is_running:
            self.logger.info("Stop signal detected at start of maybe_skip_application")
            return True

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

        # Check stop signal before AI staffing company check
        if not self.bot.is_running:
            self.logger.info("Stop signal detected before AI staffing company check")
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

        # Check stop signal before blacklist check
        if not self.bot.is_running:
            self.logger.info("Stop signal detected before blacklist check")
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
            # Check stop signal before job criteria check
            if not self.bot.is_running:
                self.logger.info("Stop signal detected before job criteria check")
                return True

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

                # Check stop signal before ATS analysis
                if not self.bot.is_running:
                    self.logger.info("Stop signal detected before ATS analysis")
                    return True

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
        For Indeed bot, we only check against the existing staffing company list.
        We don't use AI to detect new staffing companies (that's done by LinkedIn bot).

        This method is called by maybe_skip_application() after the existing list check,
        but for Indeed we simply return False since we rely only on the known list.

        Returns:
            False - Indeed bot doesn't do AI-based staffing company detection
        """
        # For Indeed, we only use the existing staffing company list
        # AI detection of new staffing companies is handled by LinkedIn bot only
        self.logger.debug(
            "Indeed bot skipping AI staffing company check - using known list only"
        )
        return False

    def _generate_ats_optimized_resume(self) -> Optional[str]:
        """
        Generate ATS-optimized resume for Indeed job application

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
