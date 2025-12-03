#!/usr/bin/env python3
"""
Start Hunting Action for LinkedIn Bot
"""

# import asyncio - removed for sync conversion
import logging
import os
import random
import sys
import time
import traceback  # noqa: E402
from typing import Any, Dict, Optional  # noqa: E402

import requests

from browser.automation import Locator  # noqa: E402

# Add parent directories to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from activity.base_activity import ActivityType  # noqa: E402
from browser.browser_operator import BrowserOperator  # noqa: E402
from constants import SERVICE_GATEWAY_URL  # noqa: E402
from linkedin_bot.actions.base_action import BaseAction  # noqa: E402
from linkedin_bot.actions.start_hunting_action.question_extractor import (  # noqa: E402
    QuestionExtractor,
)
from shared.models.application_history import ApplicationStatus  # noqa: E402
from shared.question_filler import QuestionFiller  # noqa: E402
from shared.question_filler.answer import Answer  # noqa: E402
from util.cover_letter_generator import generate_cover_letter  # noqa: E402

logger = logging.getLogger(__name__)


class StartHuntingAction(BaseAction):
    """Action to start the LinkedIn hunting process"""

    def __init__(self, bot_instance):
        super().__init__(bot_instance)
        # Initialize attributes used in job application like v1
        self.confident_to_current_application = True
        self.need_close_application_sent_popup = False
        self.workflow_run_id = (
            bot_instance.workflow_run_id
        )  # Get from bot instance  # noqa: E402
        self.cur_job_data = {}
        self.cur_job_from_submitting_queue = (
            False  # Flag to track if job is from submitting queue  # noqa: E402
        )

        # Question filler will be initialized after browser operator is ready
        self.question_filler = None

    @property
    def action_name(self) -> str:
        return "start_hunting"

    def execute(self, linkedin_starter_url: Optional[str] = None) -> Dict[str, Any]:
        """
        Start the LinkedIn hunting process
        Returns status dict with success/error info
        """
        try:
            self.logger.info(f"Starting LinkedIn bot {self.bot.bot_id}")

            if self.bot.is_running:
                return {
                    "success": False,
                    "message": "Bot is already running",
                    "status": "already_running",
                }

            # Mark as running
            self.bot.is_running = True
            self.bot.status = "running"

            # Initialize browser with bundled Chromium (sync)
            self._init_browser_and_question_filler_sync()

            self.send_activity_message("**Browser launched successfully**")

            # Build LinkedIn URL from workflow run config in DB first
            # Use frontend's linkedin_starter_url as fallback if build fails
            built_url = self._build_linkedin_url_from_db_config()
            if built_url:
                self.send_activity_message(
                    f" Opening LinkedIn search page: `{built_url}`"
                )
                self.bot.current_url = self._navigate_to_starter_page_sync(built_url)
            elif linkedin_starter_url:
                # Fallback to frontend-provided URL if build failed
                self.send_activity_message(
                    f" Opening LinkedIn starter page (fallback): `{linkedin_starter_url}`"
                )
                self.bot.current_url = self._navigate_to_starter_page_sync(
                    linkedin_starter_url
                )
            else:
                # Fallback to default LinkedIn homepage
                self.bot.current_url = self._navigate_to_linkedin_sync()
                self.send_activity_message(" **Opened LinkedIn homepage**")

            # Call login method (always check login status like v1)
            login_success, login_error = self.login_and_save_state()

            if not login_success:
                # Login failed or timed out
                self.send_activity_message(f"**Login failed:** {login_error}")
                self.send_activity_message("*Continuing with limited functionality...*")
                return {
                    "success": False,
                    "message": f"Failed to login: {login_error}",
                    "status": "error",
                }

            self.send_status_update(
                "running", "Successfully launched and navigated to LinkedIn"
            )

            # Perform job hunting steps
            self._perform_job_hunting_steps()

            # After completing the batch, automatically stop the bot
            self.logger.info(
                f"LinkedIn bot {self.bot.bot_id} completed job hunting batch"
            )

            # Send single completion message that triggers auto-stop
            self.send_activity_message(
                (  # noqa: E501
                    "**Job hunting batch completed successfully! "
                    "Ready to start a new batch.**"
                )
            )

            # Mark as not running and update status
            self.bot.is_running = False
            self.bot.status = "completed"

            # Send final status update
            self.send_status_update(
                "completed", "Job hunting batch completed successfully"
            )

            return {
                "success": True,
                "message": ("LinkedIn bot completed job hunting batch successfully"),
                "status": "completed",
                "current_url": self.bot.current_url,
            }

        except Exception as e:
            self.logger.error(f"Failed to start LinkedIn bot in execute: {e}")

            traceback.print_exc()

            # Cleanup on error
            self._cleanup_on_error()

            self.send_status_update("error", f"Failed to start: {str(e)}")

            return {
                "success": False,
                "message": f"Failed to start LinkedIn bot in execute: {str(e)}",
                "status": "error",
            }

    def handle_failed_to_apply(self, e):
        """Handle failed application - following v1's handle_failed_to_apply exactly"""
        # Delegate to the full implementation
        self._handle_failed_to_apply(e)

    def _handle_submit_button(self, next_button):
        """Handle submit button click - following v1's logic"""
        try:
            if not self.bot.browser_operator:
                raise RuntimeError("Browser operator is not initialized")

            # Check if we should actually submit (based on confidence and config)
            # Like v1: submit if confident OR if submit_confident_application is enabled
            comfortable_to_submit_confident_application = (
                self.config_reader.settings.submit_confident_application
                or self.cur_job_from_submitting_queue
            ) and self.confident_to_current_application
            should_submit = comfortable_to_submit_confident_application
            if next_button.text_content().strip().lower() == "submit application":
                status = (
                    ApplicationStatus.APPLIED.value
                    if should_submit
                    else ApplicationStatus.QUEUED.value
                )

                # Update application status like v1
                if self.application_history_tracker.cur_recording_app_history_id:
                    self.application_history_tracker.update_application(
                        self.application_history_tracker.cur_recording_app_history_id,
                        "status",
                        status,
                    )
                    self.application_history_tracker.sync_application_history()

                if should_submit:
                    self.logger.info("Clicking submit application button")
                    self.send_activity_message("**Submitting application...**")
                    self.bot.browser_operator.click_with_op(next_button)
                    time.sleep(2)

                    # Handle application sent popup
                    self._close_application_sent_popup()

                    # Update thread status to Applied before notifying UI
                    self.activity_manager.update_application_status(
                        ApplicationStatus.APPLIED.value
                    )
                    self.send_activity_message(
                        "**Application submitted successfully!**"
                    )

                    # Update application_datetime after successful submission
                    current_id = (
                        self.application_history_tracker.cur_recording_app_history_id
                    )
                    if current_id:
                        from datetime import datetime

                        self.application_history_tracker.update_application(
                            current_id,
                            "application_datetime",
                            datetime.now().isoformat(),
                        )
                        self.application_history_tracker.sync_application_history()

                else:
                    # Queue the application like v1 does
                    self.queue_application()
                    self._close_application_sent_popup()
                    self.send_activity_message("Application queued successfully!")

        except Exception as e:
            self.logger.error(f"Error handling submit button: {e}")
            # Mark as failed
            if self.application_history_tracker.cur_recording_app_history_id:
                self.application_history_tracker.update_application(
                    self.application_history_tracker.cur_recording_app_history_id,
                    "status",
                    ApplicationStatus.FAILED.value,
                )
                self.application_history_tracker.sync_application_history()
            raise Exception("No submit application button found")

    def _close_application_sent_popup(self, retry_count=4):
        """Close application sent popup - following v1's implementation"""
        while retry_count > 0:
            if self.maybe_close_application_sent_popup():
                break
            retry_count -= 1  # noqa: E501
            time.sleep(1)
        if retry_count == 0:
            self.logger.warning("No dismiss button found")

    def maybe_close_application_sent_popup(
        self, ignore_exception: bool = False
    ) -> bool:
        """Check if the popup is present and close it - using browser operator for v2"""
        # check if the popup is present
        try:
            dismiss_buttons = self.bot.page.locator(
                'button[aria-label="Dismiss"][data-test-modal-close-btn]'
            )
            closed_ctr = 0
            for dismiss_button in dismiss_buttons.all():
                if dismiss_button.count() > 0 and dismiss_button.first.is_visible():
                    # Use browser operator for clicking
                    self.bot.browser_operator.click_with_op(dismiss_button.first)
                    save_button = self.bot.page.locator(
                        '[data-control-name="save_application_btn"]'
                    )
                    if save_button.count() > 0 and save_button.first.is_visible():
                        self.bot.browser_operator.click_with_op(save_button.first)
                    closed_ctr += 1
            if closed_ctr > 0:
                return True
        except Exception:
            self.logger.warning(
                "warning did not close application sent popup or doesn't exist"
            )
        return False

    def queue_application(self):
        """Queue application for manual review - following v1's logic"""
        msg = (
            "Unconfident - Queued application because met questions that are "
            "not confident"
            if not self.confident_to_current_application
            else "Queued application"
        )
        self.logger.info(msg)

        # Update thread status to Queued
        self.activity_manager.update_application_status(ApplicationStatus.QUEUED.value)

        # Send activity message like v1 does (after status update so UI sees new state)
        activity_color = (
            "error" if not self.confident_to_current_application else "success"
        )
        self.send_activity_message(
            f"{msg}. Please check new questions in queue tab.",
            activity_type=activity_color,
        )

        # Update application status_insight like v1
        if self.application_history_tracker.cur_recording_app_history_id:
            self.application_history_tracker.update_application(
                self.application_history_tracker.cur_recording_app_history_id,
                "status_insight",
                msg,
            )
            self.application_history_tracker.sync_application_history()

    def _init_browser_and_question_filler_sync(self):
        """Initialize browser operator"""
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

        self.bot.browser_operator = BrowserOperator(headless=headless_on)

        # Set bot instance reference for stop signal detection
        self.bot.browser_operator.set_bot_instance(self.bot)

        self.bot.page = self.bot.browser_operator.start()

        if not self.bot.page:
            raise Exception("Failed to start browser operator")

        # Initialize config reader from database
        from shared.config_reader import ConfigReader  # noqa: E402

        self.config_reader = ConfigReader(
            user_id=self.bot.user_id, workflow_run_id=self.workflow_run_id
        )
        self.config_reader.load_configuration()

        # Initialize application history tracker like v1
        from shared.application_history_tracker import (  # noqa: E402
            ApplicationHistoryTracker,
        )

        self.application_history_tracker = ApplicationHistoryTracker(
            user_id=self.bot.user_id
        )

        # Initialize question filler now that browser operator is ready
        self.question_filler = QuestionFiller(  # noqa: E501
            config_reader=self.config_reader,
            application_history_tracker=self.application_history_tracker,  # noqa: E501
            submission_queue_tracker=None,  # TODO: Add submission queue tracker if needed  # noqa: E501
            activity_callback=self.send_activity_message,
            browser_operator=self.bot.browser_operator,  # Pass browser operator for page access  # noqa: E501
        )

        return True

    def _navigate_to_linkedin_sync(self):
        """Navigate to LinkedIn using browser operator"""
        if not self.bot.browser_operator:
            raise Exception("Browser operator not available")

        # Navigate to LinkedIn
        current_url = self.bot.browser_operator.navigate_to("https://www.linkedin.com")

        return current_url

    def _build_linkedin_url_from_db_config(self) -> Optional[str]:
        """Build LinkedIn search URL from workflow run config in database

        Retrieves configuration from ConfigReader (loaded from database)
        and calls service-gateway to build the LinkedIn search URL.

        Returns:
            Built LinkedIn URL or None if build failed
        """
        if not self.config_reader:
            self.logger.info("ConfigReader not initialized, cannot build LinkedIn URL")
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
                self.logger.warning("No JWT token available for LinkedIn URL building")

            # Call service-gateway endpoint to generate URL using AI
            response = requests.post(
                f"{SERVICE_GATEWAY_URL}/api/infinite-runs/generate-platform-url",
                json={"platform": "linkedin", "bot_config": bot_config},
                headers=headers,
                timeout=10,
            )

            if response.status_code == 200:
                result = response.json()
                if result.get("success") and result.get("url"):
                    built_url = result["url"]
                    self.logger.info(f"Successfully built LinkedIn URL: {built_url}")
                    return built_url
                else:
                    error_msg = result.get("error", "Unknown error")
                    self.logger.error(f"Failed to build LinkedIn URL: {error_msg}")
                    return None
            else:
                self.logger.error(
                    f"Service-gateway returned error "
                    f"{response.status_code}: {response.text}"
                )
                return None

        except Exception as e:
            self.logger.error(f"Exception while building LinkedIn URL: {e}")
            return None

    def _cleanup_on_error(self):
        """Cleanup browser resources on error"""
        try:
            if self.bot.browser_operator:
                self.bot.browser_operator.close()
        except Exception:
            pass  # Best effort cleanup

        self.bot.page = None
        self.bot.is_running = False
        self.bot.status = "error"

    def _navigate_to_starter_page_sync(self, starter_url: str):
        """Navigate to LinkedIn starter page URL"""
        if not self.bot.browser_operator:
            raise Exception("Browser operator not available")

        # Navigate to the starter page
        current_url = self.bot.browser_operator.navigate_to(starter_url)
        return current_url

    def dequeue_submitting_jobs(self):
        """
        Dequeue all jobs that are in status 'submitting' from the database for the current workflow  # noqa: E501
        Similar to v1's dequeue_submitting_jobs but uses database instead of local queue

        Returns:
            tuple[bool, str]: (keep_running, message)  # noqa: E501
        """
        try:
            # Get all jobs with 'submitting' status for current workflow
            # from database, ordered by created_at ascending
            from services.supabase_client import supabase_client

            self.logger.info(
                "Checking for jobs in submitting queue for workflow: %s",
                self.workflow_run_id,
            )
            submitting_jobs = supabase_client.get_applications_by_status_and_workflow(
                status=ApplicationStatus.SUBMITTING.value,
                workflow_run_id=self.workflow_run_id,
            )

            if not submitting_jobs:
                self.logger.info("No submitting jobs found in database")
                return True, "Success"

            job_count = len(submitting_jobs)
            self.logger.info("Found %s jobs in submitting queue", job_count)
            self.send_activity_message(
                f"**Processing {job_count} jobs from submitting queue**"
            )

            # Process each submitting job
            for job_data in submitting_jobs:
                # Check if stop was requested
                if not self.bot.is_running:
                    self.logger.info(
                        "Bot stop requested. Exiting submitting queue loop..."
                    )
                    return False, "Bot stop requested"

                job_id = job_data.get("id")
                company_name = job_data.get("company_name", "Unknown Company")
                job_title = job_data.get("job_title", "Unknown Position")
                application_url = job_data.get("application_url")

                if not application_url:  # noqa: E501
                    self.logger.warning(
                        f"No application URL found for job {job_id}, skipping"
                    )
                    continue

                company_job_title = f"{company_name} - {job_title}"
                self.send_activity_message(
                    f"**Processing queued job:** {company_job_title}"
                )

                try:
                    # Navigate to the job page
                    self.logger.info(f"Navigating to job page: {application_url}")
                    self.bot.browser_operator.navigate_to(application_url)
                    time.sleep(2)  # Give page time to load

                    # Check if we can apply to this job
                    is_apply_ready, msg = self._check_is_apply_ready()
                    if not is_apply_ready:
                        self.logger.warning(f"Job not ready for application: {msg}")
                        self.send_activity_message(f"Job not ready: {msg}")
                        continue

                    # Close any application sent popup that might be open
                    self._maybe_close_application_sent_popup(ignore_exception=True)

                    # Set flag to indicate we're processing from submitting queue
                    self.cur_job_from_submitting_queue = True

                    # Set current job data for the application process
                    self.cur_job_data = {
                        "company_name": company_name,
                        "job_title": job_title,
                        "application_url": application_url,
                        "linkedin_job_id": job_data.get("linkedin_job_id"),
                    }

                    # Set the current recording app history ID for tracking
                    self.application_history_tracker.cur_recording_app_history_id = (
                        job_id  # noqa: E501
                    )

                    # Apply to the job (pass None since we don't have a position element)  # noqa: E501
                    self._apply_to_job(pos=None)

                    # Reset flag  # noqa: E501
                    self.cur_job_from_submitting_queue = False

                    # Delete the job from submitting queue by updating status to 'applied'  # noqa: E501
                    # This will be handled by the application tracking in _apply_to_job

                    self.send_activity_message(
                        f"**Completed processing:** {company_job_title}"
                    )

                except Exception as e:
                    self.cur_job_from_submitting_queue = False

                    # Check if it's a limit exception
                    from exceptions import AIResumeLimitException  # noqa: E402
                    from exceptions import DailyLimitException  # noqa: E402
                    from exceptions import SubscriptionLimitException  # noqa: E402

                    if isinstance(e, SubscriptionLimitException):
                        self.logger.warning(f"Subscription limit reached: {e.message}")

                        # Send upgrade required message to frontend
                        self.send_websocket_message(
                            {"type": "subscription_limit_reached", "data": e.to_dict()}
                        )

                        self.send_activity_message(
                            f"**Application limit reached** - {e.message}"
                        )
                        self.send_status_update(
                            "stopped", f"Subscription upgrade required: {e.message}"
                        )

                        # Stop the bot completely (same as stop hunting action)
                        self._stop_bot_due_to_subscription_limit()

                        # Stop hunting immediately - break out of the loop
                        self.logger.info("Stopped hunting due to subscription limit")
                        return False, f"Subscription limit reached: {e.message}"
                    elif isinstance(e, DailyLimitException):
                        self.logger.warning(f"Daily limit reached: {e.message}")

                        # Send daily limit message to frontend
                        self.send_websocket_message(
                            {"type": "daily_limit_reached", "data": e.to_dict()}
                        )

                        self.send_activity_message(
                            f"**Daily limit reached** - {e.message}"
                        )
                        self.send_status_update(
                            "stopped", f"Daily limit reached: {e.message}"
                        )

                        # Stop the bot completely
                        self._stop_bot_due_to_subscription_limit()

                        # Stop hunting immediately - break out of the loop
                        self.logger.info("Stopped hunting due to daily limit")
                        return False, f"Daily limit reached: {e.message}"
                    elif isinstance(e, AIResumeLimitException):
                        self.logger.warning(f"AI resume limit reached: {e.message}")

                        # Send AI resume limit message to frontend
                        self.send_websocket_message(
                            {"type": "ai_resume_limit_reached", "data": e.to_dict()}
                        )

                        self.send_activity_message(
                            f"**AI Resume limit reached** - {e.message}"
                        )
                        self.send_status_update(
                            "stopped", f"AI Resume limit reached: {e.message}"
                        )

                        # Stop the bot completely
                        self._stop_bot_due_to_subscription_limit()

                        # Stop hunting immediately - break out of the loop
                        self.logger.info("Stopped hunting due to AI resume limit")
                        return False, f"AI resume limit reached: {e.message}"

                    self.logger.error(f"Failed to process submitting job {job_id}: {e}")
                    self.send_activity_message(
                        f"**Failed to process:** {company_job_title} - {str(e)}"
                    )

                    # Update job status to failed  # noqa: E501
                    if self.application_history_tracker.cur_recording_app_history_id:
                        self.application_history_tracker.update_application(
                            self.application_history_tracker.cur_recording_app_history_id,  # noqa: E501
                            "status",
                            ApplicationStatus.FAILED.value,  # noqa: E501
                        )
                        self.application_history_tracker.update_application(
                            self.application_history_tracker.cur_recording_app_history_id,  # noqa: E501
                            "status_insight",
                            f"Failed during dequeue processing: {str(e)}",
                        )
                        self.application_history_tracker.sync_application_history()

                    # Continue with next job rather than failing entirely
                    continue

            self.send_activity_message("**Finished processing submitting queue**")
            return True, "Success"

        except Exception as e:
            self.logger.error(f"Error in dequeue_submitting_jobs: {e}")
            self.send_activity_message(
                f"Error processing submitting queue: {str(e)}"
            )  # noqa: E501
            return False, str(e)

    def _maybe_close_application_sent_popup(self, ignore_exception: bool = False):
        """
        Close application sent popup if present - following v1's maybe_close_application_sent_popup  # noqa: E501

        Args:
            ignore_exception: Whether to ignore exceptions when clicking

        Returns:
            bool: True if popup was closed, False otherwise
        """
        try:
            page = self.bot.page
            if not page or page.is_closed():
                return False

            # Look for dismiss buttons like v1 does
            dismiss_buttons = page.locator(
                'button[aria-label="Dismiss"][data-test-modal-close-btn]'
            )

            closed_ctr = 0
            for dismiss_button in dismiss_buttons.all():
                try:
                    if dismiss_button.count() > 0 and dismiss_button.is_visible():
                        # Click dismiss button
                        dismiss_button.click(timeout=2000)

                        # Look for save button and click it if present
                        save_button = page.locator(
                            '[data-control-name="save_application_btn"]'
                        )
                        if save_button.count() > 0 and save_button.first.is_visible():
                            save_button.first.click(timeout=2000)

                        closed_ctr += 1

                except Exception as e:
                    if not ignore_exception:
                        self.logger.warning(f"Error clicking dismiss button: {e}")
                    continue

            if closed_ctr > 0:
                self.logger.info(f"Closed {closed_ctr} application sent popup(s)")
                return True

        except Exception as e:
            if not ignore_exception:
                self.logger.warning(f"Error closing application sent popup: {e}")

        return False

    def _perform_job_hunting_steps(self):
        """Perform the core job hunting steps"""
        try:
            # First, process any jobs in the submitting queue
            keep_running, msg = self.dequeue_submitting_jobs()
            if not keep_running:
                return False, msg

            self.send_activity_message("**Running job search batch...**")

            # Get job listings from current page
            self.logger.info("Starting to get job listings from current page...")
            job_listings = self._get_job_listings()

            if job_listings:
                self.send_activity_message(
                    f"**Found {len(job_listings)} job listings** on current page"
                )
                job_count = len(job_listings)
                self.logger.info(
                    "Successfully retrieved %s job listing elements",
                    job_count,
                )

                # Apply to jobs - following v1's exact flow
                keep_running, msg = self._apply_to_jobs(job_listings)
                if not keep_running:
                    # failed to apply due to no quota or browser closed
                    self.send_activity_message(msg)
                    return False, msg
            else:
                self.send_activity_message("**No job listings found** on current page")
                self.logger.warning(
                    "No job listings were returned from _get_job_listings()"
                )
                return True, "No jobs found"

            # Job hunting steps completed successfully - don't send message here
            # Final completion message will be sent by the main execute method

        except Exception as e:
            self.logger.error(f"Error in job hunting steps: {e}")
            self.send_activity_message(f"Error during job hunting: {str(e)}")
            # Error case - don't send completion message here
            # Final completion message will be sent by the main execute method

    def has_signed_in_profile_button(self) -> bool:
        """Check if user is signed in by looking for profile button (like v1)"""
        try:
            page = self.bot.page
            if (
                not page
                or not self.bot.browser_operator
                or not self.bot.browser_operator.is_ready()
            ):
                return False

            # Look for the profile menu trigger button (same as v1 logic)
            profile_button = page.locator(".global-nav__primary-link-me-menu-trigger")

            # Check if button exists and is visible
            button_count = profile_button.count()
            if button_count == 0:
                return False

            # Check if first button is visible
            first_button = profile_button.first
            is_visible = first_button.is_visible()

            return is_visible and button_count >= 1

        except Exception as e:
            self.logger.error(f"Error checking profile button: {e}")
            return False

    def wait_for_finishing_sign_in(self, timeout: int = 300) -> tuple[bool, str]:
        """Wait for user to finish signing in (like v1's logic)"""
        import time  # noqa: E402

        start_time = time.time()

        while not self.has_signed_in_profile_button():
            # Check if stop was requested
            if not self.bot.is_running:
                error_msg = "Bot stop requested during sign-in"
                self.send_activity_message(f"{error_msg}")
                return False, error_msg

            # Check for timeout
            if time.time() - start_time > timeout:
                error_msg = f"Sign in timeout after {timeout} seconds"
                self.send_activity_message(f"{error_msg}")
                return False, error_msg

            # Check if page is still available
            if not self.bot.page or self.bot.page.is_closed():
                error_msg = "Browser closed before sign in finished"
                self.send_activity_message(f"{error_msg}")
                return False, error_msg

            # Send periodic updates
            elapsed = int(time.time() - start_time)
            self.send_activity_message(f"Waiting for login... ({elapsed}s/{timeout}s)")

            # Wait 2 seconds before checking again (like v1)
            self.bot.page.wait_for_timeout(2000)

        return True, ""

    def login_and_save_state(self):
        """Login to LinkedIn and save storage state (like v1's login method)"""
        try:
            self.send_activity_message("Checking login status...")

            # Check if already logged in
            if self.has_signed_in_profile_button():
                self.send_activity_message("Already logged in!")
                return True, ""

            # Need to login
            self.send_activity_message("Not logged in - please login manually")
            self.send_activity_message("Starting login timer...")

            # Wait for user to finish signing in
            success, error = self.wait_for_finishing_sign_in(timeout=300)  # 5 minutes

            if not success:
                return False, error

            self.send_activity_message("Login successful!")

            return True, ""

        except Exception as e:
            error_msg = f"Login process failed: {str(e)}"
            self.logger.error(error_msg)
            self.send_activity_message(error_msg)
            return False, error_msg

    def _get_job_listings(self) -> list:
        """Get job listings from current page - identical to v1's get_page_listings"""

        def get_scroll_area_height():
            """Get the height of the scroll area containing job listings"""
            try:
                posting_card_section = page.locator(
                    "div.scaffold-layout__list:not(:has(span:text("
                    "'Jobs you may be interested in')))"
                )
                scroll_area = posting_card_section.locator(
                    "ul:has(li.ember-view):not(:has(li[data-test-pagination-page-btn]))"
                    ":has(.job-card-container--clickable)"
                )

                if scroll_area.count() == 0:
                    self.logger.warning("No postings found since scroll area not found")
                    return 0

                bounding_box = scroll_area.bounding_box()
                if bounding_box:
                    height = bounding_box.get("height", 0)
                    return height
                return 0
            except Exception as e:
                self.logger.debug(f"Error getting scroll area height: {e}")
                return 0

        try:
            page = self.bot.page
            if not page:
                return []

            if not self.bot.browser_operator:
                self.logger.error("Browser operator not available")
                return []

            max_attempts = 2
            attempts = 0
            self.logger.info("Getting page listings")

            while True:
                # Check if stop was requested
                if not self.bot.is_running:
                    self.logger.info(
                        "Bot stop requested. Exiting job listings scroll loop..."
                    )
                    return []

                try:
                    # Select the first job listing
                    self.logger.debug("Looking for job cards...")
                    job_card = page.locator(".job-card-container--clickable")
                    job_card_count = job_card.count()
                    self.logger.debug(f"Found {job_card_count} job cards")

                    if job_card_count > 0:
                        self.logger.debug("Clicking last job card...")
                        self.bot.browser_operator.click_with_op(job_card.last)
                        height = get_scroll_area_height()
                        if height == 0:
                            raise Exception("No postings found")

                        delta_y = 800
                        scroll_step = int(height // delta_y + 1)
                        self.logger.debug(
                            f" Will scroll {scroll_step} times to load all listings"
                        )

                        # scroll down slowly
                        for i in range(scroll_step):
                            scroll_amount = height / scroll_step
                            self.logger.debug(
                                f" Scroll step {i+1}/{scroll_step}, amount: {scroll_amount:.1f}px"  # noqa: E501
                            )
                            self.bot.browser_operator.scroll_with_op(
                                delta_x=0, delta_y=int(scroll_amount)
                            )
                            # Random delay like v1
                            delay = random.randint(1, 3) / 10
                            time.sleep(delay)
                            height = get_scroll_area_height()
                    else:
                        raise Exception("No job card found")
                    break

                except Exception as e:
                    self.logger.error(
                        f"get_page_listings Error attempt {attempts}: {e}"
                    )
                    attempts += 1
                    if attempts >= max_attempts:
                        self.logger.error("Max attempts reached. Exiting.")
                        break
                    elif page.is_closed():
                        self.logger.error("Page has been closed manually. Exiting...")
                        break
                    time.sleep(5)

            # get all listings again after loading js
            self.logger.debug("Re-collecting all job listings after scrolling...")
            all_listings_locator = page.locator(".job-card-container--clickable")
            final_count = all_listings_locator.count()
            self.logger.debug(f"Final count of job listings: {final_count}")

            all_listings = all_listings_locator.all()
            self.logger.info(f"collected {len(all_listings)} listings")

            # Verify we got actual elements
            if all_listings:
                self.logger.debug(
                    f"Successfully collected {len(all_listings)} job listing elements"
                )
                # Test first element to make sure it's valid
                try:
                    first_element = all_listings[0]
                    is_visible = first_element.is_visible()
                    self.logger.debug(f"First job element visible: {is_visible}")
                except Exception as e:
                    self.logger.debug(f"Could not check first element visibility: {e}")
            else:
                self.logger.warning("No job listing elements were collected!")

            return all_listings

        except Exception as e:
            self.logger.error(f"Error getting job listings: {e}")
            return []

    def _apply_to_jobs(self, pos_list) -> tuple[bool, str]:
        """Apply to jobs - identical to v1's apply_to_jobs method"""
        # go over pos_list and apply to each job
        for pos in pos_list:
            # Check if stop was requested
            self.logger.debug(
                f"Checking is_running: {self.bot.is_running}, bot id={id(self.bot)}"
            )
            if not self.bot.is_running:
                self.logger.info("Bot stop requested. Exiting job application loop...")
                return False, "Bot stop requested"

            # Check if browser is still connected (like v1 checks browser_session)
            if not self.bot.page or self.bot.page.is_closed():
                self.logger.info("Browser has been closed manually. Exiting...")
                return False, "Browser has been closed manually. Exiting..."
            try:
                # Check if we're ready to apply (simple check)
                is_apply_ready, msg = self._check_is_apply_ready()
                if not is_apply_ready:
                    return False, msg
                self._maybe_close_application_sent_popup(ignore_exception=True)
                self._apply_to_job(pos)
            except Exception as e:
                # Check if it's a limit exception
                from exceptions import AIResumeLimitException  # noqa: E402
                from exceptions import DailyLimitException  # noqa: E402
                from exceptions import SubscriptionLimitException  # noqa: E402

                if isinstance(e, SubscriptionLimitException):
                    self.logger.warning(f"Subscription limit reached: {e.message}")

                    # Send upgrade required message to frontend
                    self.send_websocket_message(
                        {"type": "subscription_limit_reached", "data": e.to_dict()}
                    )

                    self.send_activity_message(
                        f"**Application limit reached** - {e.message}"
                    )
                    self.send_status_update(
                        "stopped", f"Subscription upgrade required: {e.message}"
                    )

                    # Stop the bot completely (same as stop hunting action)
                    self._stop_bot_due_to_subscription_limit()

                    # Stop hunting immediately - break out of the loop
                    self.logger.info("Stopped hunting due to subscription limit")
                    return False, f"Subscription limit reached: {e.message}"
                elif isinstance(e, DailyLimitException):
                    self.logger.warning(f"Daily limit reached: {e.message}")

                    # Send daily limit message to frontend
                    self.send_websocket_message(
                        {"type": "daily_limit_reached", "data": e.to_dict()}
                    )

                    self.send_activity_message(f"**Daily limit reached** - {e.message}")
                    self.send_status_update(
                        "stopped", f"Daily limit reached: {e.message}"
                    )

                    # Stop the bot completely
                    self._stop_bot_due_to_subscription_limit()

                    # Stop hunting immediately - break out of the loop
                    self.logger.info("Stopped hunting due to daily limit")
                    return False, f"Daily limit reached: {e.message}"
                elif isinstance(e, AIResumeLimitException):
                    self.logger.warning(f"AI resume limit reached: {e.message}")

                    # Send AI resume limit message to frontend (triggers subscription modal)
                    self.send_websocket_message(
                        {"type": "ai_resume_limit_reached", "data": e.to_dict()}
                    )

                    self.send_activity_message(
                        f"**AI Resume limit reached** - {e.message}"
                    )
                    self.send_status_update(
                        "stopped", f"AI Resume limit reached: {e.message}"
                    )

                    # Stop the bot completely
                    self._stop_bot_due_to_subscription_limit()

                    # Stop hunting immediately - break out of the loop
                    self.logger.info("Stopped hunting due to AI resume limit")
                    return False, f"AI resume limit reached: {e.message}"

                self._handle_failed_to_apply(e)
                continue
        return True, "Success"

    def _check_is_apply_ready(self) -> tuple[bool, str]:
        """Check if ready to apply - simplified version of v1's check_is_apply_ready"""
        # For now, we'll implement a basic version
        # In full implementation, this would check quota and trial limits like v1
        self.logger.debug("Checking if ready to apply...")

        # Basic checks - can be expanded later with quota system  # noqa: E501
        if not self.bot.page or self.bot.page.is_closed():  # noqa: E501
            self.send_activity_message("Browser page is not available")
            return False, "Browser page is not available"

        # TODO: Add quota checking like v1 does with session.check_quota_and_maybe_refresh()  # noqa: E501
        # TODO: Add trial limit checking like v1 does with check_if_limited_by_free_trial()  # noqa: E501

        return True, "Success"

    def _handle_failed_to_apply(self, e):
        """Handle failed application - following v1's handle_failed_to_apply exactly"""
        # Check if error is due to browser/page closure (interrupted, not failed)
        error_str = str(e).lower()
        is_browser_closed = (
            "target page, context or browser has been closed" in error_str
            or "browser has been closed" in error_str
            or "context has been closed" in error_str
        )

        if is_browser_closed:
            self.logger.warning(
                "Application interrupted due to browser closure - skipping failure tracking"
            )
            error_msg = f"Application interrupted: {str(e)}"
            self.send_activity_message(f"{error_msg}")
            # Don't mark as failed, mark as interrupted
            # Don't send Slack notification for interruptions
            # Send Mixpanel with different event
            try:
                self._send_mixpanel_interrupted_application(e)
            except Exception as mixpanel_error:
                self.logger.warning(f"Failed to send Mixpanel event: {mixpanel_error}")

            # Print traceback for debugging
            self.logger.info(traceback.format_exc())
            return

        self.logger.error(f"Failed to apply to job: {e}")
        # Normal failure handling (not interrupted)
        # Log the error with job info if available
        error_msg = f"Failed to apply to job: {str(e)}"
        self.send_activity_message(f"{error_msg}")
        self.activity_manager.update_application_status(ApplicationStatus.FAILED.value)

        # Update application history
        if self.application_history_tracker.cur_recording_app_history_id:
            self.application_history_tracker.update_application(
                self.application_history_tracker.cur_recording_app_history_id,
                "status",
                ApplicationStatus.FAILED.value,
            )
            self.application_history_tracker.sync_application_history()

        # Capture screenshot
        screenshot_path = None
        screenshot_url = None
        try:
            if self.bot.page and self.bot.browser_operator:
                self.logger.info("Taking screenshot of failed application...")
                screenshot_path = self.bot.browser_operator.take_screenshot(
                    self.bot.page
                )
                if screenshot_path:
                    self.logger.info(f"Screenshot saved to: {screenshot_path}")
                    screenshot_url = self._upload_screenshot_to_blob(screenshot_path)
                    if screenshot_url:
                        self.logger.info(f"Screenshot uploaded to: {screenshot_url}")
                    else:
                        self.logger.warning(
                            "Screenshot upload failed - no URL returned"
                        )
                else:
                    self.logger.warning("Screenshot capture returned None")
            else:
                self.logger.warning(
                    f"Cannot take screenshot - page: {self.bot.page is not None}, browser_operator: {self.bot.browser_operator is not None}"
                )
        except Exception as screenshot_error:
            self.logger.warning(f"Failed to capture screenshot: {screenshot_error}")

        # Send Mixpanel event via service-gateway
        try:
            self._send_mixpanel_failed_application(e, screenshot_url)
        except Exception as mixpanel_error:
            self.logger.warning(f"Failed to send Mixpanel event: {mixpanel_error}")

        # Send Slack notification via service-gateway
        try:
            self._send_slack_failed_notification(e, screenshot_url)
        except Exception as slack_error:
            self.logger.warning(f"Failed to send Slack notification: {slack_error}")

        # Print full traceback
        self.logger.error(traceback.format_exc())

    def _apply_to_job(self, pos):
        """Apply to a single job - following v1's apply_to_job method exactly"""
        try:
            # Check if browser operator is available
            if not self.bot.browser_operator:
                raise RuntimeError("Browser operator is not initialized")

            # Handle jobs from submitting queue differently (pos will be None)
            if not self.cur_job_from_submitting_queue and pos:
                # Click on the job position (like v1 does with self.op(pos.click))
                self.logger.debug("Clicking on job position...")
                self.bot.browser_operator.click_with_op(pos)
                time.sleep(1)  # Give page time to load

            # Check if we're in search mode (browse only, no applications)
            is_search_mode = getattr(self.config_reader.settings, "search_mode", False)

            # Get position info first (needed for both modes)
            if not self.cur_job_from_submitting_queue:
                pos_info_success = self._maybe_get_pos_info(job_card=pos)
                if not pos_info_success:
                    self.logger.warning(
                        "Could not extract job information or job already processed"
                    )
                    return

            # Create activity message like v1 does with company and title
            # For submitting queue jobs, cur_job_data is already set in dequeue method
            company = getattr(self, "cur_job_data", {}).get(
                "company_name", "Unknown Company"
            )
            title = getattr(self, "cur_job_data", {}).get(
                "job_title", "Unknown Position"
            )
            line = f"{company} - {title}"
            padding = 5
            border = "-" * int(len(line) + padding * 2)
            activity_text = (
                f"\n{border}\n{' ' * padding}{line}{' ' * padding}\n{border}\n"
            )

            self.send_activity_message(activity_text)

            # Check if we should skip this application
            # (like v1's maybe_skip_application)
            should_skip = False
            if not self.cur_job_from_submitting_queue:
                should_skip = self.maybe_skip_application()
            if should_skip:
                self.logger.info(f"Skipping application to {company} - {title}")
                # Add status update like v1 does
                if self.application_history_tracker.cur_recording_app_history_id:
                    self.application_history_tracker.update_application(
                        self.application_history_tracker.cur_recording_app_history_id,
                        "status",
                        ApplicationStatus.SKIPPED.value,
                    )
                    self.application_history_tracker.sync_application_history()
                return  # Skip this application

            # In search mode, queue the job after skip check passes
            if is_search_mode:
                # Mark as queued (saved for later review) in search mode
                if self.application_history_tracker.cur_recording_app_history_id:
                    self.application_history_tracker.update_application(
                        self.application_history_tracker.cur_recording_app_history_id,
                        "status",
                        ApplicationStatus.QUEUED.value,
                    )
                    self.application_history_tracker.update_application(
                        self.application_history_tracker.cur_recording_app_history_id,
                        "status_insight",
                        "Saved in search mode (not applied)",
                    )
                    self.application_history_tracker.sync_application_history()

                # Update thread status to Queued (like other search agents)
                self.activity_manager.update_application_status(
                    ApplicationStatus.QUEUED.value
                )

                # Send activity message (consistent with other search agents)
                self.send_activity_message(f"Queued: {company} | {title}")
                return

            # Set confidence flag like v1
            self.confident_to_current_application = True

            # Click on easy apply button - following v1's logic
            easy_apply_button = self._maybe_get_easy_apply_button()
            if not easy_apply_button:  # noqa: E501
                self.logger.info(
                    "No easy apply button found or already applied or has closed the application page"  # noqa: E501
                )
                self.send_activity_message(
                    "No easy apply button found - job may not support easy apply or already applied"  # noqa: E501
                )
                # Add application history tracking like v1 does
                if self.application_history_tracker.cur_recording_app_history_id:
                    self.application_history_tracker.update_application(
                        self.application_history_tracker.cur_recording_app_history_id,
                        "status",
                        ApplicationStatus.FAILED.value,
                    )
                    self.application_history_tracker.update_application(
                        self.application_history_tracker.cur_recording_app_history_id,
                        "status_insight",
                        "No longer accepting applications",  # noqa: E501
                    )
                    self.application_history_tracker.sync_application_history()
                return

            # Click easy apply button like v1 does
            self.logger.info("Starting application process...")

            self.send_activity_message(
                f"Starting application to {company}", ActivityType.ACTION
            )
            self.bot.browser_operator.click_with_op(easy_apply_button)
            time.sleep(1)

            # Handle safety reminder popup like v1
            self._maybe_popup_safety_reminder()

            # Process application form like v1
            self.logger.info("Processing application form...")
            self.send_activity_message(
                "Filling out application form...", ActivityType.ACTION
            )

            # Process the application form
            next_button = self.process_application_form()

            # The form processing returns the submit button
            if next_button and next_button.count() > 0:
                button_text = next_button.text_content()
                if "submit" in button_text.lower():
                    self.send_activity_message(
                        "Application form completed",
                        ActivityType.RESULT,
                    )
                    # Handle submit button like v1 does
                    self._handle_submit_button(next_button)
                else:
                    self.send_activity_message(
                        "Application form completed", ActivityType.RESULT
                    )
                    # Form not ready to submit - mark as failed
                    self.activity_manager.update_application_status(
                        ApplicationStatus.FAILED.value
                    )
                    app_id = (
                        self.application_history_tracker.cur_recording_app_history_id
                    )
                    if app_id:
                        self.application_history_tracker.update_application(
                            app_id,
                            "status",
                            ApplicationStatus.FAILED.value,
                        )
                        self.application_history_tracker.sync_application_history()
            else:
                # No button found - mark as failed
                self.send_activity_message(
                    "No submit button found", ActivityType.RESULT
                )
                self.activity_manager.update_application_status(
                    ApplicationStatus.FAILED.value
                )
                if self.application_history_tracker.cur_recording_app_history_id:
                    self.application_history_tracker.update_application(
                        self.application_history_tracker.cur_recording_app_history_id,
                        "status",
                        ApplicationStatus.FAILED.value,
                    )
                    self.application_history_tracker.sync_application_history()
                raise Exception("No submit application button found")

        except Exception as e:
            self.logger.error(f"Error in _apply_to_job: {e}")
            self.handle_failed_to_apply(e)
            raise  # Re-raise so _handle_failed_to_apply can handle it

    def _maybe_get_easy_apply_button(self):
        """Get easy apply button - following v1's maybe_get_easy_apply_button exactly"""
        time.sleep(0.8)  # Like v1's time.sleep(0.8)

        easy_apply_button = self.bot.page.locator(".jobs-apply-button--top-card")
        button_count = easy_apply_button.count()

        if button_count > 0:
            self.logger.debug(f"Found {button_count} apply buttons")

            if button_count > 1:
                # Multiple buttons - check each one like v1 does
                buttons = easy_apply_button.all()
                for button in buttons:
                    try:
                        text_content = button.text_content()
                        if text_content:
                            text_lower = text_content.lower().strip()
                            is_easy_apply_button = (
                                "easy" in text_lower or "continue" in text_lower
                            )
                            if is_easy_apply_button:
                                # Check if the button is disabled like v1 does
                                if button.is_disabled():
                                    self.logger.info(
                                        "Easy apply button is disabled, checking next"
                                    )
                                    continue
                                self.logger.debug(
                                    f"Found valid easy apply button: {text_lower}"
                                )
                                return button
                    except Exception as e:
                        self.logger.debug(f"Error checking button: {e}")
                        continue
            else:
                # Single button - check if it's valid
                button = easy_apply_button.first
                try:
                    if not button.is_disabled():
                        text_content = button.text_content()
                        self.logger.debug(f"Found single apply button: {text_content}")
                        return button
                except Exception as e:
                    self.logger.debug(f"Error checking single button: {e}")

        self.logger.info("No easy apply button found")
        return None

    def _maybe_get_pos_info(self, job_card=None) -> bool:
        """Get position info - following v1's maybe_get_pos_info structure"""
        try:
            # Extract position information like v1's PositionInfoExtractor
            position_data = self._get_position_info(job_card=job_card)

            if not position_data:
                return False

            # Check if this job has already been processed (duplicate detection)
            app_history_id = position_data.get("application_history_id")
            if app_history_id:
                # Check if job already exists in database
                # TODO: Optimize this by checking just existence rather than full record
                existing_job = (
                    self.application_history_tracker.get_job_item_from_history(
                        app_history_id
                    )
                )
                if existing_job:
                    company = position_data.get("company_name", "Unknown Company")
                    title = position_data.get("job_title", "Unknown Position")
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

                    # Send activity message about skipping
                    self.activity_manager.start_application_thread(
                        company, title, existing_status
                    )
                    if existing_status in reprocessable_statuses:
                        msg = (
                            f"Skipping {company} - {title} "
                            f"(already processed with status: {existing_status})"
                        )
                        self.send_activity_message(msg, activity_type="result")

                        log_msg = (
                            f"Skipping job {company} - {title} - "
                            f"already exists in database with status: "
                            f"{existing_status}"
                        )
                        self.logger.info(log_msg)
                        return False
                    else:
                        # Allow reprocessing for these statuses
                        msg = (
                            f"Reprocessing {company} - {title} "
                            f"(previous status: {existing_status})"
                        )
                        self.send_activity_message(msg, activity_type="action")

                        log_msg = (
                            f"Reprocessing job {company} - {title} - "
                            f"previous status was: {existing_status}"
                        )
                        self.logger.info(log_msg)

            # Set current job data like v1 does
            self.cur_job_data = position_data

            # Add application history tracking like v1 does
            if app_history_id:
                # Update application history with position data (like v1 does)
                for attr_name, attr_value in position_data.items():
                    self.application_history_tracker.update_application(
                        app_history_id, attr_name, attr_value
                    )

                # Set current recording job ID
                self.application_history_tracker.cur_recording_app_history_id = (
                    app_history_id
                )

                self.logger.debug(
                    f"Updated application history for job: {app_history_id}"
                )

                try:
                    self.application_history_tracker.create_application_history()
                except Exception as create_error:
                    # Check if it's a limit exception
                    from exceptions import DailyLimitException  # noqa: E402
                    from exceptions import SubscriptionLimitException  # noqa: E402

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

            self.logger.debug(f"Position info extracted: {position_data}")
            return True

        except Exception as e:
            # Check if it's a limit exception
            from exceptions import DailyLimitException  # noqa: E402
            from exceptions import SubscriptionLimitException  # noqa: E402

            if isinstance(e, (SubscriptionLimitException, DailyLimitException)):
                # Propagate limit exceptions to stop hunting
                raise
            self.logger.error(f"Error getting position info: {e}")
            return False

    def _get_position_info(self, job_card) -> dict:
        """Extract position information using v2's async PositionInfoExtractor"""
        try:
            page = self.bot.page
            if not page:
                return {}

            # Use the new async PositionInfoExtractor
            from linkedin_bot.position_info_extractor import (  # pylint: disable=import-error
                position_info_extractor,
            )

            PositionInfoExtractor = position_info_extractor.PositionInfoExtractor

            position_info_extractor = PositionInfoExtractor(page)

            # Get comprehensive position information
            data = position_info_extractor.get_position_info(
                job_card=job_card,
                workflow_run_id=self.workflow_run_id,
                user_id=self.bot.user_id,
            )

            if data:
                company = data.get("company_name")
                title = data.get("job_title")
                self.logger.info(
                    f"Successfully extracted position info: {company} - {title}"
                )
            else:
                self.logger.warning("No position info extracted")

            return data

        except Exception as e:
            self.logger.error(f"Error extracting position info: {e}")
            return {}

    def _maybe_popup_safety_reminder(self):
        # check if the safety reminder is present
        safety_reminder = self.bot.page.get_by_role(
            "button",
            name="I understand the tips and want to continue the apply process",
        )

        if safety_reminder.count() > 0:
            self.logger.info("Clicking safety reminder")
            self.bot.browser_operator.click_with_op(safety_reminder.first)
        else:
            self.logger.info("No safety reminder found")

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
        job_title = self.cur_job_data.get("job_title", "Unknown Position")

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
                    f"Skipping {company_name} - {job_title} (manually removed)",
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
        self.send_activity_message(f"Evaluating {company_name} - {job_title}", "action")

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
                f"Skipping {company_name} - {job_title} (known staffing company)"
            )
            self.send_activity_message(skip_reason, "result")

            self.activity_manager.start_application_thread(
                company_name, job_title, ApplicationStatus.SKIPPED.value
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
                    f"Skipping {company_name} - {job_title} (staffing company)"
                )
                self.send_activity_message(skip_reason, "result")

                self.activity_manager.start_application_thread(
                    company_name, job_title, ApplicationStatus.SKIPPED.value
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
            skip_reason = f"Skipping {company_name} - company is blacklisted"
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
                msg = f"Skipping {company_name} - doesn't match job criteria"
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
        self.send_activity_message(f" **AI Thinking:** {text}", "thinking")

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
            # Only generate here in search mode - apply mode generates during upload step
            is_search_mode = getattr(self.config_reader.settings, "search_mode", False)
            if (
                is_search_mode
                and self.config_reader.settings.generate_ats_optimized_resume
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

    def _create_op_wrapper(self):
        """
        Create an operation wrapper that uses the browser operator's
        wrapper methods.
        """

        def op_wrapper(func, *args, **kwargs):
            if self.bot.browser_operator and hasattr(self.bot.browser_operator, "op"):
                return self.bot.browser_operator.op(func, *args, **kwargs)
            else:
                # Fallback to direct function call if browser operator not ready
                return func(*args, **kwargs)

        return op_wrapper

    def process_application_form(self):
        """
        Process the job application form after clicking Easy Apply
        Based on v1's process_application_form method
        Returns True if form was processed successfully
        """
        try:
            if not self.question_filler:
                self.logger.warning(
                    "Question filler not initialized, form processing may be limited"
                )

            self.send_activity_message("Processing application form", "action")

            page = self.bot.page
            next_button = self._get_next_button()
            section_count = 0
            max_sections = 12  # Prevent infinite loops

            while (
                section_count < max_sections
                and next_button.count() > 0
                and (next_button.text_content()).strip().lower() != "submit application"
                or section_count == 0
            ):
                # Check if page is still available
                if page.is_closed():
                    self.logger.info("Page has been closed manually. Exiting...")
                    raise Exception("Page has been closed manually. Exiting...")

                # Scroll down slowly like v1
                self._scroll_form_slowly()

                # Check current section and process it
                current_section = self._check_current_section()
                self.send_activity_message(
                    f"**Processing {current_section} section**", "action"
                )

                if current_section == "contact_info":
                    self._fill_contact_info_section()
                elif current_section == "resume":
                    self._fill_resume_section()
                elif current_section == "additional_questions":
                    self._fill_additional_questions_section()
                elif current_section == "privacy_policy":
                    self._fill_privacy_policy_section()
                elif current_section == "education":
                    self._fill_education_section()
                else:
                    # Default to additional questions processing
                    self._fill_additional_questions_section()

                # Check if we're at submit button
                next_button = self._get_next_button()
                if (
                    next_button.is_visible()
                    and (next_button.text_content()).strip().lower()
                    == "submit application"
                ):
                    break

                # Click next button and continue
                time.sleep(1)
                section_count += 1

                if next_button.is_visible():
                    msg = (
                        f"Finished section {current_section}, " f"clicking next button"
                    )
                    self.send_activity_message(msg, "action")
                    self.bot.browser_operator.click_with_op(next_button)
                else:
                    raise Exception("No next button found")

                next_button = self._get_next_button()

            # Return the final next/submit button
            self.send_activity_message("Form processing completed", "result")
            return next_button

        except Exception as e:
            self.logger.error(f"Error processing application form: {e}")
            msg = f"Error processing form: {str(e)}"
            self.send_activity_message(msg, "result")
            self.activity_manager.update_application_status(
                ApplicationStatus.FAILED.value
            )
            raise

    def _get_next_button(self) -> Locator:
        # check if the button is next or rev
        next_button = self.bot.page.get_by_role("button", name="Next")
        if next_button.count() == 0:
            next_button = self.bot.page.get_by_role("button", name="Review")
            if next_button.count() == 0:
                next_button = self.bot.page.get_by_role(
                    "button", name="Submit application"
                )
                if next_button.count() == 0:
                    raise Exception(
                        f"No next button found in {self._get_next_button.__name__}"
                    )
        return next_button.first

    def _scroll_form_slowly(self):
        """Scroll down slowly like v1 does"""
        for _ in range(20):
            self.bot.browser_operator.scroll_with_op(delta_x=0, delta_y=100)
            time.sleep(random.randint(1, 3) / 10)

    def _check_current_section(self) -> str:
        """
        Determine what section of the form we're currently on.
        Matches v1's check_current_section.
        """
        page = self.bot.page

        try:
            # div has attribute data-test-modal
            easy_apply_modal = page.locator("div[data-test-modal]")
            if easy_apply_modal.count() == 0:
                return "unknown"
            easy_apply_modal = easy_apply_modal.first

            # check if the current section is the contact info section
            if (
                easy_apply_modal.locator("h3").filter(has_text="Contact info").count()
                > 0
            ):
                return "contact_info"
            elif easy_apply_modal.locator("h3").filter(has_text="Resume").count() > 0:
                return "resume"
            elif (
                easy_apply_modal.locator("h3")
                .filter(has_text="Additional Questions")
                .count()
                > 0
            ):
                return "additional_questions"
            elif (
                easy_apply_modal.locator("h3").filter(has_text="Privacy policy").count()
                > 0
            ):
                return "privacy_policy"
            elif (
                easy_apply_modal.locator("h3").filter(has_text="Education").count() > 0
            ):
                return "education"
            else:
                return "unknown"
        except Exception as e:
            self.logger.error(f"Error checking current section: {e}")
            return "unknown"

    def _fill_contact_info_section(self):
        """Fill contact information sectio"""
        page = self.bot.page

        # Find all form elements in this section
        try:
            questions = page.locator(".fb-dash-form-element").all()
            for question in questions:
                try:
                    question_extractor = QuestionExtractor.create(question)
                    if question_extractor.required:
                        # Use the current recording job ID from
                        # application history tracker
                        app_id = (
                            self.application_history_tracker.cur_recording_app_history_id
                        )
                        current_job_id = app_id if app_id else "unknown_job_id"
                        answer = self.question_filler.fill_question(
                            question,
                            question_extractor.question_text,
                            question_extractor.question_type,
                            current_job_id,
                        )
                    self.confident_to_current_application = (
                        answer.confident and self.confident_to_current_application
                    )
                except Exception as e:
                    logger.warning(f"Failed to process question element: {e}")
                    continue
        except Exception as e:
            logger.error(f"Failed to find form elements: {e}")
            return

        # Also handle resume upload in contact info section
        self._fill_resume_section(fill_additional_questions=False)

    def _fill_resume_section(self, fill_additional_questions=True):
        self._upload_resume()
        # maybe there are additional questions in the resume section
        if fill_additional_questions:
            self._fill_additional_questions_section()
        self._maybe_remove_cover_letter()
        self._maybe_upload_cover_letter()

    def _upload_resume(self):
        upload_resume_buttons = self.bot.page.get_by_role("button", name="Upload")
        for i, button in enumerate(upload_resume_buttons.all()):
            # check text = "Upload resume"
            if "upload resume" in button.text_content().strip().lower():
                # check if the resume path exists
                is_valid_resume = self.config_reader.is_valid_resume()
                if not is_valid_resume:
                    ats_template = self.config_reader.using_valid_ats_resume_template
                    regular_resume = self.config_reader.using_valid_resume
                    msg = (
                        f"Failed to upload resume due to "
                        f"{ats_template=} or {regular_resume=}"
                    )
                    logger.error(msg)
                    self.send_activity_message(msg)
                    raise Exception(msg)
                # Default to user's regular resume
                resume_path = self.config_reader.profile.resume_path

                # Generate ATS-optimized resume if enabled and template available
                if (
                    self.config_reader.settings.generate_ats_optimized_resume
                    and self.config_reader.profile.ats_resume_template
                ):
                    # Check if job is from submission queue and has
                    # existing ATS resume
                    app_id = (
                        self.application_history_tracker.cur_recording_app_history_id
                    )
                    if self.cur_job_from_submitting_queue and app_id:
                        self.send_activity_message(
                            "Checking for existing ATS resume...", "action"
                        )
                        existing_resume_path = self._get_existing_ats_resume_pdf()

                        if existing_resume_path:
                            # Validate the path before using it
                            if self._is_valid_resume_path(existing_resume_path):
                                resume_path = existing_resume_path
                                self.send_activity_message(
                                    "Using existing ATS-optimized resume", "result"
                                )
                            else:
                                msg = (
                                    f"Existing ATS resume path is invalid: {existing_resume_path}. "
                                    "Skipping this application."
                                )
                                logger.error(msg)
                                self.send_activity_message(msg, "result")
                                raise Exception(msg)
                        else:
                            raise Exception("No existing ATS-optimized resume found")
                    else:
                        # Generate new ATS resume for non-queue jobs
                        self.send_activity_message(
                            "Generating ATS-optimized resume...", "action"
                        )
                        optimized_resume_path = self._generate_ats_optimized_resume()

                        if optimized_resume_path:
                            # Validate the generated path before using it
                            if self._is_valid_resume_path(optimized_resume_path):
                                resume_path = optimized_resume_path
                                msg = "ATS-optimized resume generated successfully"
                                self.send_activity_message(msg, "result")
                            else:
                                msg = (
                                    f"Generated ATS resume path is invalid: {optimized_resume_path}. "
                                    "Skipping this application."
                                )
                                logger.error(msg)
                                self.send_activity_message(msg, "result")
                                raise Exception(msg)
                        else:
                            msg = (
                                "Failed to generate ATS-optimized resume. "
                                "Skipping this application."
                            )
                            logger.error(msg)
                            self.send_activity_message(msg, "result")
                            raise Exception(msg)
                else:
                    # Using regular resume - validate it
                    if not self._is_valid_resume_path(resume_path):
                        msg = (
                            f"Regular resume path is invalid: '{resume_path}'. "
                            "Skipping this application."
                        )
                        logger.error(msg)
                        self.send_activity_message(msg, "result")
                        raise Exception(msg)

                # Create a temporary copy with normalized name for LinkedIn upload
                temp_resume_path = self._create_temp_resume_for_upload(resume_path)

                self.bot.browser_operator.set_input_files_with_op(
                    self.bot.page.locator("input[type='file']").nth(i),
                    files=str(temp_resume_path),
                )

                # Update application history with resume path (like v1 does)
                app_id = self.application_history_tracker.cur_recording_app_history_id
                if app_id:
                    generate_ats = (
                        self.config_reader.settings.generate_ats_optimized_resume
                    )
                    if not generate_ats and self.config_reader.profile.resume_id:
                        # update the resume_id if this is not an
                        # ATS optimized resume
                        self.application_history_tracker.update_application(
                            app_id,
                            "resume_id",
                            str(self.config_reader.profile.resume_id),
                        )
                    elif (
                        generate_ats
                        and self.config_reader.profile.selected_ats_template_id
                    ):
                        # update the resume_id if this is an ATS optimized resume
                        template_id = (
                            self.config_reader.profile.selected_ats_template_id
                        )
                        self.application_history_tracker.update_application(
                            app_id,
                            "ats_template_id",
                            str(template_id),
                        )
                    else:
                        logger.warning("No resume_id or ats_template_id found")

                # Send success message
                self.send_activity_message("Resume uploaded successfully", "result")
                self.application_history_tracker.sync_application_history()
                break

    def _maybe_remove_cover_letter(self):
        cover_letter_header = self.bot.page.locator("h3:has-text('cover letter')")
        if cover_letter_header.count() == 0:
            return False
        cover_letter_area = cover_letter_header.locator("..")
        clear_button = cover_letter_area.locator("button[aria-label='Clear document']")
        if clear_button.count() >= 1:
            self.send_activity_message(
                "Removing cover letter due to inability to generate a customized PDF"
            )
            self.bot.browser_operator.click_with_op(clear_button.first)
            return True
        return False

    def _maybe_upload_cover_letter(self):
        cover_letter_header = self.bot.page.locator("h3:has-text('cover letter')")
        if (
            cover_letter_header.count() > 0
            and self.config_reader.application.generate_cover_letter
        ):
            self.upload_cover_letter()

    def upload_cover_letter(self):
        """
        Upload cover letter - similar to v1 implementation
        Generates cover letter PDF if it doesn't exist, then uploads it
        """
        import os  # noqa: E402

        from constants import COVER_LETTER_DIR  # noqa: E402

        # Check if cover letter already exists in submission queue
        cover_letter_pdf_path = None
        cover_letter_id = None
        if (
            self.cur_job_from_submitting_queue
            and self.application_history_tracker.cur_recording_app_history_id
        ):
            self.send_activity_message(
                "Checking for existing cover letter...", "action"
            )
            cover_letter_pdf_path = self._get_existing_cover_letter_pdf()

            if cover_letter_pdf_path:
                self.send_activity_message("Using existing cover letter", "result")

                # Extract cover letter ID from application history
                # for existing cover letters
                app_id = self.application_history_tracker.cur_recording_app_history_id
                app_data = self.application_history_tracker.application_history.get(
                    app_id, {}
                )
                questions_and_answers = app_data.get("questions_and_answers", [])

                # Find the cover letter question to get the ID
                for qa in questions_and_answers:
                    question = qa.get("question", "").lower()
                    if "upload cover letter" in question:
                        cover_letter_id = qa.get("answer")
                        self.logger.info(
                            f"Found existing cover letter ID: {cover_letter_id}"
                        )
                        break

        # If not found in queue, generate new cover letter
        if not cover_letter_pdf_path or not os.path.exists(cover_letter_pdf_path):
            self.logger.info(f"Generating cover letter for {self.cur_job_data}")

            # Generate filename similar to v1
            company_name = (
                self.cur_job_data.get("company_name", "").lower().replace(" ", "_")
            )
            to_whom = (
                self.cur_job_data.get("hiring_team", {})
                .get("name", "")
                .lower()
                .replace(" ", "_")
            )

            if not to_whom:
                file_name = f"cover_letter_to_{company_name}.pdf"
            else:
                file_name = f"cover_letter_to_{to_whom}_from_{company_name}.pdf"

            cover_letter_pdf_path = os.path.join(COVER_LETTER_DIR, file_name)

            # Generate cover letter using the v2 utility
            try:
                self.send_activity_message(
                    f"Generating cover letter for {company_name}"
                )

                app_id = self.application_history_tracker.cur_recording_app_history_id
                (
                    _,
                    actual_pdf_path,
                    cover_letter_id,
                ) = generate_cover_letter(
                    position_info=self.cur_job_data,
                    config_reader=self.config_reader,
                    activity_callback=self.send_activity_message,
                    pdf_path=cover_letter_pdf_path,
                    application_history_id=app_id,
                )

                if actual_pdf_path and os.path.exists(actual_pdf_path):
                    cover_letter_pdf_path = actual_pdf_path
                    self.send_activity_message(f"Cover letter generated: {file_name}")
                else:
                    self.send_activity_message("Failed to generate cover letter PDF")
                    return False

            except Exception as e:
                self.logger.error(f"Failed to generate cover letter: {e}")
                self.send_activity_message(f"Cover letter generation failed: {str(e)}")
                return False

        # Ensure we have a valid PDF file to upload
        if not cover_letter_pdf_path or not os.path.exists(cover_letter_pdf_path):
            self.send_activity_message("No cover letter PDF found to upload")
            return False

        self.send_activity_message(
            f" Uploading cover letter: {os.path.basename(cover_letter_pdf_path)}"
        )

        # Find cover letter upload section
        cover_letter_header = self.bot.page.locator("h3:has-text('cover letter')")
        if cover_letter_header.count() == 0:
            self.send_activity_message("Cover letter upload section not found")
            return False

        cover_letter_area = cover_letter_header.locator("..")
        # get the input with type = "file"
        file_input = cover_letter_area.locator("input[type='file']")
        if file_input.count() == 0:
            self.send_activity_message("Cover letter file input not found")
            return False

        file_input = file_input.first

        try:
            self.bot.browser_operator.set_input_files_with_op(
                file_input, files=str(cover_letter_pdf_path)
            )
            self.send_activity_message("Cover letter uploaded successfully")

            # Log the cover letter upload to application history (matching v1)
            current_id = self.application_history_tracker.cur_recording_app_history_id
            if current_id:
                from shared.question_filler.faq_question_type_mapping import (  # noqa: E402
                    get_faq_question_type,
                )
                from shared.question_filler.question_type import (  # noqa: E402
                    QuestionType,
                )

                # Create log entry matching v1's format
                new_log = {
                    "question": "upload cover letter",
                    "question_type": get_faq_question_type(QuestionType.INPUT),
                    "answer": cover_letter_id,
                    "reference": "",
                    "confident": True,
                    "ai_generated": True,
                }

                # Get existing Q&A list for this job
                job_data = self.application_history_tracker.application_history
                history_qna = job_data.get(current_id, {}).get(
                    "questions_and_answers", []
                )

                # Append new Q&A to existing list and deduplicate
                updated_qna = history_qna + [new_log]
                deduplicated_qna = (
                    self.application_history_tracker.deduplicate_questions_and_answers(
                        updated_qna
                    )
                )

                self.application_history_tracker.update_application(
                    current_id,
                    "questions_and_answers",
                    deduplicated_qna,
                )

            return True
        except Exception as e:
            self.logger.error(f"Failed to upload cover letter: {e}")
            self.send_activity_message(f"Cover letter upload failed: {str(e)}")
            return False

    def _fill_additional_questions_section(self):
        """Fill additional questions section"""
        # Use the current recording job ID from application history tracker
        cur_app_history_id = (
            self.application_history_tracker.cur_recording_app_history_id
            if self.application_history_tracker.cur_recording_app_history_id
            else "unknown_job_id"
        )
        for question in self.bot.page.locator(".fb-dash-form-element").all():
            question_extractor = QuestionExtractor.create(question)
            is_cover_letter_question = (
                "cover letter" in question_extractor.question_text.strip().lower()
            )
            if (
                is_cover_letter_question
                and self.config_reader.settings.generate_cover_letter
            ):
                answer = self.fill_cover_letter_question(
                    question,
                    question_extractor.question_text,
                    question_extractor.question_type,
                    cur_app_history_id,
                    self.cur_job_data,
                )
            elif (
                question_extractor.required
                or not self.config_reader.settings.skip_optional_questions
            ):
                # Handle regular question inline
                try:
                    # Use the question filler to handle the question
                    answer = self.question_filler.fill_question(
                        question,
                        question_extractor.question_text,
                        question_extractor.question_type,
                        cur_app_history_id,
                    )

                    self.confident_to_current_application = (
                        answer.confident and self.confident_to_current_application
                    )

                except Exception as e:
                    q_text = question_extractor.question_text
                    logger.error(f"Error filling question '{q_text}': {e}")

            elif (
                not question_extractor.required
                and self.config_reader.settings.skip_optional_questions
            ):
                # remove the answer from optional questions to prevent it
                # from being filled
                self.empty_question(
                    question,
                    question_extractor.question_text,
                    question_extractor.question_type,
                    cur_app_history_id,
                )

    def _fill_privacy_policy_section(self):
        """Fill privacy policy section - usually just checkboxes"""
        page = self.bot.page

        # Find and check all checkboxes
        checkboxes = page.locator('input[type="checkbox"]')
        checkbox_count = checkboxes.count()

        for i in range(checkbox_count):
            checkbox = checkboxes.nth(i)
            is_checked = checkbox.is_checked()

            if not is_checked:
                self.bot.browser_operator.click_with_op(checkbox)
                self.send_activity_message("Accepted privacy policy")

    def _fill_education_section(self):
        """Fill education section"""
        self.send_activity_message(" Processing education section")
        # Education section usually has dropdowns and inputs
        self._fill_additional_questions_section()

    def _extract_question_text(self, element) -> str:
        """Extract question text from form element"""
        try:
            # Try different selectors for question text
            selectors = [
                "label",
                ".fb-form-element-label",
                ".t-14",
                "[data-test-form-element-label]",
                ".jobs-easy-apply-form-element__label",
            ]

            for selector in selectors:
                text_element = element.locator(selector).first
                if text_element.count() > 0:
                    text = text_element.text_content()
                    if text and text.strip():
                        return text.strip()

            # Fallback to element text
            return element.text_content() or "Unknown question"

        except Exception as e:
            self.logger.error(f"Error extracting question text: {e}")
            return "Unknown question"

    def _is_valid_resume_path(self, resume_path: str) -> bool:
        """
        Validate that the resume path is a valid PDF file.

        Args:
            resume_path: Path to the resume file

        Returns:
            True if the path is a valid PDF file, False otherwise
        """
        from pathlib import Path  # noqa: E402

        try:
            path = Path(resume_path)

            # Check if path exists
            if not path.exists():
                logger.error(f"Resume path does not exist: {resume_path}")
                return False

            # Check if it's a file (not a directory)
            if not path.is_file():
                logger.error(f"Resume path is not a file: {resume_path}")
                return False

            # Check if it's a PDF file
            if path.suffix.lower() != ".pdf":
                logger.error(
                    f"Resume is not a PDF file: {resume_path} (extension: {path.suffix})"
                )
                return False

            return True

        except Exception as e:
            logger.error(f"Error validating resume path: {e}")
            return False

    def _create_temp_resume_for_upload(self, original_resume_path: str) -> str:
        """
        Create a temporary copy of the resume with a normalized name
        for LinkedIn upload. Reuses the same temp file location,
        overwriting each time.

        Args:
            original_resume_path: Path to the original resume file

        Returns:
            Path to the temporary resume file with normalized name
        """
        import shutil  # noqa: E402
        import tempfile  # noqa: E402
        from pathlib import Path  # noqa: E402

        try:
            # Use a fixed temp location that gets overwritten each time
            temp_dir = tempfile.gettempdir()

            # Create normalized filename
            original_path = Path(original_resume_path)
            file_extension = original_path.suffix or ".pdf"
            normalized_filename = f"resume{file_extension}"
            temp_resume_path = os.path.join(temp_dir, normalized_filename)

            # Remove existing temp file if it exists, then copy the new one
            if os.path.exists(temp_resume_path):
                os.remove(temp_resume_path)

            shutil.copy2(original_resume_path, temp_resume_path)

            # Send activity message to frontend
            msg = (
                f"**Uploading resume as** `Resume{file_extension}` "
                f"**for professional appearance**"
            )
            self.send_activity_message(msg)

            logger.info(f"Created/updated temporary resume copy: {temp_resume_path}")
            return temp_resume_path

        except Exception as e:
            logger.error(f"Failed to create temporary resume copy: {e}")
            # Fallback to original path if temp creation fails
            msg = "Using original resume filename for upload"
            self.send_activity_message(msg)
            return original_resume_path

    def _cleanup_temp_resume(self, temp_resume_path: str) -> None:
        """
        Clean up temporary resume file and directory

        Args:
            temp_resume_path: Path to the temporary resume file to clean up
        """
        try:
            from pathlib import Path  # noqa: E402

            temp_path = Path(temp_resume_path)
            temp_dir = temp_path.parent

            # Remove the temporary file
            if temp_path.exists():
                temp_path.unlink()
                msg = f"Cleaned up temporary resume file: {temp_resume_path}"
                logger.info(msg)

            # Remove the temporary directory if empty
            if temp_dir.exists() and not any(temp_dir.iterdir()):
                temp_dir.rmdir()
                logger.info(f"Cleaned up temporary directory: {temp_dir}")

        except Exception as e:
            logger.warning(f"Failed to cleanup temporary resume files: {e}")

    def fill_cover_letter_question(
        self,
        question: Locator,
        question_text: str,
        question_type: str,
        app_history_id: str,
        position_info: dict,
    ) -> Answer:
        """
        Fill a cover letter question

        Args:
            question: The question locator element
            question_text: Text of the question
            question_type: Type of question
            app_history_id: Application history ID for tracking
            position_info: Position information for cover letter generation

        Returns:
            Answer object with cover letter content
        """
        try:
            msg = f"Generating cover letter for: {question_text}"
            self.send_activity_message(msg)

            # Generate a basic cover letter
            cover_letter = self._generate_basic_cover_letter(position_info)

            # Create filler and fill the question
            filler = self.question_filler.construct_question_filler(
                question, question_text, question_type, app_history_id
            )

            answer = Answer(cover_letter, "", True)
            filler.fill_value(answer)

            self.send_activity_message("Cover letter generated and filled")
            return answer

        except Exception as e:
            logger.error(f"Error filling cover letter question '{question_text}': {e}")
            # Return empty answer on error
            return Answer("", "", False)

    def empty_question(
        self,
        question: Locator,
        question_text: str,
        question_type: str,
        app_history_id: str,
    ):
        """
        Empty/skip an optional question

        Args:  # noqa: E501
            question: The question locator element
            question_text: Text of the question
            question_type: Type of question
            app_history_id: Application history ID for tracking
        """
        try:
            self.send_activity_message(f"Skipping optional question: {question_text}")

            # Create filler and fill with empty value
            filler = self.question_filler.construct_question_filler(
                question, question_text, question_type, app_history_id
            )

            empty_answer = Answer("", "", False)
            filler.fill_value(empty_answer)

        except Exception as e:
            logger.error(f"Error emptying question '{question_text}': {e}")

    def _generate_basic_cover_letter(self, position_info: dict) -> str:
        """
        Generate a basic cover letter based on position info using
        v2 cover letter generator.

        Args:
            position_info: Dictionary containing job/position information

        Returns:
            Basic cover letter text
        """
        # Use the new cover letter generator utility
        cover_letter_text, _, _ = generate_cover_letter(
            position_info=position_info,
            config_reader=self.config_reader,
            activity_callback=self.send_activity_message,
        )
        return cover_letter_text

    def _generate_ats_optimized_resume(self) -> Optional[str]:
        """
        Generate ATS-optimized resume following the same flow as frontend Step 4->5

        Returns:
            Path to generated optimized resume PDF, or None if generation failed
        """
        try:
            import tempfile  # noqa: E402
            from pathlib import Path  # noqa: E402

            import requests  # noqa: E402

            from services.jwt_token_manager import jwt_token_manager  # noqa: E402

            # Get job description from cur_job_data
            job_description = self.cur_job_data.get("pos_context", "")
            if not job_description:
                msg = "No job description available for ATS optimization"
                logger.warning(msg)
                return None

            # Get additional skills from ATS template (loaded from database)
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
            # (already done in analyze_ats_score)
            initial_ats_score = self.cur_job_data.get("initial_ats_score", 0)
            initial_ats_alignments = self.cur_job_data.get("initial_ats_alignments", [])
            keywords_to_add = self.cur_job_data.get("keywords_to_add", [])
            missing_requirements = self.cur_job_data.get("missing_requirements", [])

            msg = f"Initial ATS Score: {initial_ats_score}/100"
            self.send_activity_message(msg, "result")

            # Step 2: Check which missing requirements can be addressed
            # with additional skills
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
                    f"Skills check failed: {skills_response.status_code} - {skills_response.text}"  # noqa: E501
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

            # Step 3: Generate optimized resume using only addressable requirements
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

            # Check for AI resume limit (402 Payment Required)
            if create_response.status_code == 402:
                from exceptions import AIResumeLimitException  # noqa: E402

                try:
                    error_data = create_response.json()
                    detail = error_data.get("detail", {})
                    raise AIResumeLimitException(
                        message=detail.get(
                            "message",
                            "AI resume limit reached for your plan",
                        ),
                        plan_tier=detail.get("plan_tier", "free"),
                        limit=detail.get("limit", 0),
                        current_usage=detail.get("current_usage", 0),
                    )
                except AIResumeLimitException:
                    raise
                except Exception as parse_error:
                    logger.error(f"Failed to parse 402 response: {parse_error}")
                    raise AIResumeLimitException(
                        message="AI resume limit reached for your plan",
                        plan_tier="free",
                        limit=0,
                        current_usage=0,
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

            # Step 4: Analyze final ATS score with optimized resume using ATSMarker
            self.send_activity_message("Validating improvements...", "action")

            # Create ATSMarker for final analysis with optimized HTML
            from bs4 import BeautifulSoup  # noqa: E402

            from shared.ats_marker import ATSMarker  # noqa: E402
            from shared.ats_marker.defs import ApplicantData, JobData  # noqa: E402

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

            # Run final ATS analysis using ATSMarker
            final_ats_marker = ATSMarker(
                final_job_data,
                final_applicant_data,
                user_token=token,
            )

            try:
                final_ats_score, final_alignments_objects, _ = final_ats_marker.run()

                # Convert Alignment objects to dict format for storage
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
                    f" Final ATS Score: {final_ats_score}/100 "
                    f"(Improvement: +{ats_improvement})"
                )
                self.send_activity_message(msg, "result")

            except Exception as e:
                logger.error(f"Final ATS analysis failed: {e}")
                # Fallback to initial values
                final_ats_score = initial_ats_score
                final_ats_alignments = []
                ats_improvement = 0

                msg = (
                    f"Final validation failed, using initial score: "
                    f"{final_ats_score}/100"
                )
                self.send_activity_message(msg, "warning")

            # Step 5: Store all results in application history
            # (mapping example_* fields)
            app_id = self.application_history_tracker.cur_recording_app_history_id
            if app_id:
                app_id = self.application_history_tracker.cur_recording_app_history_id

                # Store all ATS analysis results in application history
                updates = {
                    # Initial ATS Analysis (Before Optimization) - maps to example_* in ATS template  # noqa: E501
                    "ats_score": initial_ats_score,  # noqa: E501
                    "ats_alignments": initial_ats_alignments,
                    "ats_keyword_to_add_to_resume": keywords_to_add,
                    # Final ATS Analysis (After Optimization) - maps to example_optimized_* in ATS template  # noqa: E501
                    "optimized_ats_score": final_ats_score,
                    "optimized_ats_alignments": final_ats_alignments,
                    # Skills Check Analysis - maps to example_* in ATS template
                    "missing_requirements": missing_requirements,
                    "addressable_requirements": addressable_requirements,
                    "skills_check_thinking": skills_check_thinking,
                    # Resume Generation Data
                    "ats_resume_id": ats_resume_id,
                    "ats_template_id": template_id,  # Store template ID for original HTML lookup
                }

                # Update all fields
                for field, value in updates.items():
                    self.application_history_tracker.update_application(
                        app_id, field, value
                    )

                # Sync to database
                self.application_history_tracker.sync_application_history()

                logger.info(
                    f"Stored complete ATS analysis in application history: {app_id}"
                )

            # Step 6: Convert optimized HTML to PDF for upload
            self.send_activity_message(
                "Converting optimized resume to PDF...", "action"
            )

            # Use the PDF generator utility  # noqa: E501
            from util.pdf_generator import generate_pdf_from_html  # noqa: E402

            # Create temporary directory for the optimized resume PDF
            temp_dir = Path(tempfile.mkdtemp())
            company_name = (
                self.cur_job_data.get("company_name", "")
                .replace(" ", "_")
                .lower()  # noqa: E501
            )
            job_title = self.cur_job_data.get("job_title", "").replace(" ", "_").lower()
            pdf_filename = f"optimized_resume_{company_name}_{job_title}"  # No .pdf extension, function adds it  # noqa: E501

            # Generate PDF from optimized HTML
            try:
                optimized_pdf_path = generate_pdf_from_html(
                    html_content=optimized_html,
                    output_dir=temp_dir,
                    filename=pdf_filename,
                )

                if optimized_pdf_path and optimized_pdf_path.exists():
                    logger.info(f"Generated optimized resume PDF: {optimized_pdf_path}")

                    # Step 7: Upload PDF to blob storage and update ATS resume record
                    self.send_activity_message(
                        " Uploading optimized resume to cloud storage...", "action"
                    )

                    try:
                        # Upload PDF to blob storage via service gateway
                        blob_url = self._upload_pdf_to_blob_storage(
                            optimized_pdf_path, ats_resume_id
                        )

                        if blob_url:
                            logger.info(f"Uploaded PDF to blob storage: {blob_url}")

                            # Update ATS resume record with blob_url
                            success = self._update_ats_resume_blob_url(
                                ats_resume_id, blob_url
                            )  # noqa: E501
                            if success:
                                logger.info(
                                    f"Updated ATS resume {ats_resume_id} with blob_url"
                                )
                            else:
                                logger.warning(
                                    "Failed to update ATS resume with blob_url"
                                )  # noqa: E501
                        else:
                            logger.warning(
                                "Failed to upload PDF to blob storage, but resume generation succeeded"  # noqa: E501
                            )

                    except Exception as upload_error:
                        logger.error(
                            f"Error uploading PDF to blob storage: {upload_error}"
                        )
                        # Don't fail the entire process if upload fails

                    return str(optimized_pdf_path)
                else:
                    logger.error("Failed to generate optimized resume PDF")
                    return None
            except Exception as e:
                logger.error(f"Error generating PDF: {e}")
                return None

        except Exception as e:
            # Re-raise AIResumeLimitException so it can be handled by the caller
            from exceptions import AIResumeLimitException  # noqa: E402

            if isinstance(e, AIResumeLimitException):
                raise

            logger.error(f"Error generating ATS-optimized resume: {e}")
            import traceback  # noqa: E402

            logger.error(f"Traceback: {traceback.format_exc()}")
            return None

    def _upload_pdf_to_blob_storage(self, pdf_path: str, ats_resume_id: str) -> str:
        """Upload generated PDF to blob storage via service gateway"""
        try:
            import requests  # noqa: E402

            # Get auth token
            from services.jwt_token_manager import jwt_token_manager  # noqa: E402

            token = jwt_token_manager.get_token()
            if not token:
                logger.error("No auth token available for blob upload")
                return None

            # Read the PDF file
            with open(pdf_path, "rb") as f:
                pdf_content = f.read()

            # Create form data for file upload
            filename = f"ats_resume_{ats_resume_id}.pdf"
            files = {"file": (filename, pdf_content, "application/pdf")}
            data = {"folder": "ats_resumes"}  # Organize in specific folder

            # Upload to service gateway blob endpoint
            response = requests.post(
                f"{SERVICE_GATEWAY_URL}/api/blob/upload",
                headers={"Authorization": f"Bearer {token}"},
                files=files,
                data=data,
            )

            if response.status_code == 200:
                result = response.json()
                if result.get("success"):
                    return result.get("blob_url")
                else:
                    logger.error(f"Blob upload failed: {result}")
                    return None
            else:
                logger.error(
                    f"Blob upload HTTP error {response.status_code}: {response.text}"
                )
                return None

        except Exception as e:
            logger.error(f"Error uploading PDF to blob storage: {e}")
            return None

    def _update_ats_resume_blob_url(self, ats_resume_id: str, blob_url: str) -> bool:
        """Update ATS resume record with blob_url via service gateway"""
        try:
            import requests  # noqa: E402

            # Get auth token
            from services.jwt_token_manager import jwt_token_manager  # noqa: E402

            token = jwt_token_manager.get_token()
            if not token:
                logger.error("No auth token available for ATS resume update")
                return False

            # Update ATS resume record
            update_payload = {"blob_url": blob_url}

            response = requests.patch(
                f"{SERVICE_GATEWAY_URL}/api/ats-resume/{ats_resume_id}",
                headers={
                    "Authorization": f"Bearer {token}",  # noqa: E501
                    "Content-Type": "application/json",
                },
                json=update_payload,
            )

            if response.status_code == 200:
                result = response.json()
                return result.get("success", False)
            else:
                log_msg = (
                    f"ATS resume update HTTP error {response.status_code}: "
                    f"{response.text}"
                )
                logger.error(log_msg)
                return False

        except Exception as e:
            logger.error(f"Error updating ATS resume blob_url: {e}")
            return False

    def _get_existing_ats_resume_pdf(self) -> Optional[str]:
        """
        Check if ATS resume already exists for current job from submission
        queue. If exists, read optimized HTML, convert to PDF, upload to
        blob, and return path.

        Returns:
            Path to existing ATS resume PDF, or None if not found/failed
        """
        try:
            import requests  # noqa: E402

            from services.jwt_token_manager import jwt_token_manager  # noqa: E402

            # Get current application history ID
            app_history_id = (
                self.application_history_tracker.cur_recording_app_history_id
            )
            if not app_history_id:
                logger.warning("No application history ID available")
                return None

            app_data = self.application_history_tracker.application_history.get(
                app_history_id, {}
            )
            ats_resume_id = app_data.get("ats_resume_id")
            if not ats_resume_id:
                logger.warning("No ats_resume_id found for application history ID")
                return None

            logger.info(f"Found existing ats_resume_id: {ats_resume_id}")

            # Get auth token
            token = jwt_token_manager.get_token()
            if not token:
                logger.warning("No JWT token available for ATS resume check")
                return None

            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }

            # Get ATS resume directly by ID (much more efficient!)
            url = f"{SERVICE_GATEWAY_URL}/api/ats-resume/{ats_resume_id}"
            response = requests.get(url, headers=headers)

            if response.status_code != 200:
                msg = f"ATS resume {ats_resume_id} not found or not accessible"
                logger.info(msg)
                return None

            result = response.json()
            if not result.get("success"):
                error_msg = result.get("message", "Unknown error")
                msg = f"Failed to get ATS resume {ats_resume_id}: {error_msg}"
                logger.info(msg)
                return None

            optimized_html = result.get("optimized_html")

            logger.info(f"Retrieved ATS resume {ats_resume_id} successfully")

            # Use current template HTML if optimized_html is empty or None
            # Skip re-evaluation and directly generate PDF
            if not optimized_html:
                logger.info(
                    f"No optimized HTML found in ATS resume {ats_resume_id}, "
                    "using current template HTML instead"
                )
                template_html = self.config_reader.profile.ats_resume_template
                if not template_html:
                    msg = (
                        f"No optimized HTML found in ATS resume {ats_resume_id} "
                        "and no template HTML available"
                    )
                    logger.warning(msg)
                    return None
                optimized_html = template_html
                logger.info(
                    "Using template HTML to generate PDF (skipping re-evaluation)"
                )

            logger.info("Generating fresh PDF from current optimized HTML")

            # Generate PDF from optimized HTML
            import tempfile  # noqa: E402
            from pathlib import Path  # noqa: E402

            from util.pdf_generator import generate_pdf_from_html  # noqa: E402

            # Create output directory
            temp_dir = Path(tempfile.gettempdir())
            output_dir = temp_dir / "ats_resumes"
            output_dir.mkdir(exist_ok=True)

            # Generate PDF filename
            filename = f"existing_ats_resume_{ats_resume_id}"

            # Generate PDF
            pdf_path = generate_pdf_from_html(optimized_html, output_dir, filename)

            if not pdf_path or not pdf_path.exists():
                logger.error(
                    "Failed to generate PDF from existing optimized HTML"
                )  # noqa: E402
                return None

            logger.info(f"Generated PDF from existing HTML: {pdf_path}")  # noqa: E402

            # Upload fresh PDF to blob storage
            self.send_activity_message(
                "Uploading updated ATS resume to storage...", "action"
            )

            try:
                blob_url = self._upload_pdf_to_blob_storage(
                    str(pdf_path), ats_resume_id
                )

                if blob_url:
                    logger.info(f"Uploaded existing ATS resume PDF to blob: {blob_url}")

                    # Update ATS resume record with blob_url
                    success = self._update_ats_resume_blob_url(ats_resume_id, blob_url)
                    if success:
                        logger.info(f"Updated ATS resume {ats_resume_id} with blob_url")
                    else:
                        logger.warning("Failed to update ATS resume with blob_url")
                else:
                    logger.warning("Failed to upload PDF to blob storage")

            except Exception as upload_error:
                logger.error(f"Error uploading existing ATS resume PDF: {upload_error}")
                # Don't fail the process if upload fails

            return str(pdf_path)

        except Exception as e:
            logger.error(f"Error checking for existing ATS resume: {e}")
            return None

    def _get_existing_cover_letter_pdf(self) -> Optional[str]:
        """
        Check if cover letter already exists for current job from submission
        queue. If exists, download from blob URL and return local path.

        Returns:
            Path to existing cover letter PDF, or None if not found/failed
        """
        try:
            import tempfile  # noqa: E402
            from pathlib import Path  # noqa: E402

            import requests  # noqa: E402

            from services.jwt_token_manager import jwt_token_manager  # noqa: E402

            # Get current application history ID
            app_history_id = (
                self.application_history_tracker.cur_recording_app_history_id
            )
            if not app_history_id:
                logger.warning("No application history ID available")
                return None

            # Look for cover letter question in application history
            app_data = self.application_history_tracker.application_history.get(
                app_history_id, {}
            )
            questions_and_answers = app_data.get("questions_and_answers", [])

            # Find the cover letter question
            cover_letter_id = None
            for qa in questions_and_answers:
                question = qa.get("question", "").lower()
                if "cover letter" in question or "upload cover" in question:
                    cover_letter_id = qa.get("answer")
                    break

            if not cover_letter_id:
                logger.info("No cover letter ID found in application history")
                return None

            logger.info(f"Found existing cover letter ID: {cover_letter_id}")

            # Get auth token
            token = jwt_token_manager.get_token()
            if not token:
                msg = "No JWT token available for cover letter check"
                logger.warning(msg)
                return None

            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }

            # Get cover letter details by ID
            url = (
                f"{SERVICE_GATEWAY_URL}/api/cover-letter/"
                f"generated/{cover_letter_id}"
            )
            response = requests.get(url, headers=headers)

            if response.status_code != 200:
                msg = f"Cover letter {cover_letter_id} " f"not found or not accessible"
                logger.info(msg)
                return None

            result = response.json()
            if not result.get("success"):
                error_msg = result.get("message", "Unknown error")
                msg = f"Failed to get cover letter {cover_letter_id}: " f"{error_msg}"
                logger.info(msg)
                return None

            cover_letter_data = result.get("cover_letter", {})
            blob_url = cover_letter_data.get("cover_letter_url")
            file_name = cover_letter_data.get(
                "file_name", f"cover_letter_{cover_letter_id}.pdf"
            )

            if not blob_url:
                logger.warning(f"No blob URL found for cover letter {cover_letter_id}")
                return None

            logger.info(
                f"Retrieved cover letter {cover_letter_id} with blob URL: {blob_url}"
            )

            # Download PDF from blob storage
            self.send_activity_message("Downloading existing cover letter...", "action")

            # Create temp directory for cover letters
            temp_dir = Path(tempfile.gettempdir())
            output_dir = temp_dir / "cover_letters"
            output_dir.mkdir(exist_ok=True)

            # Download the PDF
            pdf_response = requests.get(blob_url)
            if pdf_response.status_code != 200:
                logger.error(f"Failed to download cover letter PDF from {blob_url}")
                return None

            # Save to local file
            local_pdf_path = output_dir / file_name
            with open(local_pdf_path, "wb") as f:
                f.write(pdf_response.content)

            logger.info(f"Downloaded cover letter PDF to: {local_pdf_path}")
            return str(local_pdf_path)

        except Exception as e:
            logger.error(f"Error checking for existing cover letter: {e}")
            return None

    def _check_if_staffing_company(self) -> bool:
        """
        Check if the current job posting is from a staffing/recruiting company.
        Opens the company page in a new tab to avoid navigating away from the posting.

        Returns:
            True if it's a staffing company, False otherwise
        """
        new_page = None

        try:
            self.logger.info("Checking if company is a staffing agency...")
            self.send_activity_message(
                "Checking if company is a staffing agency...", ActivityType.ACTION
            )

            # Find the company link (contains /company/ in href)
            top_card = 'div[class*="job-details-jobs-unified-top-card__container"]'
            all_links = self.bot.page.locator(top_card).locator("a")

            if all_links.count() == 0:
                self.logger.warning(
                    "No links found in top card, assuming not staffing company"
                )
                return False

            # Find the company link URL
            company_url = None  # noqa: E501
            for i in range(all_links.count()):
                link = all_links.nth(i)
                href = link.get_attribute("href")
                if href and "/company/" in href:
                    company_url = href
                    self.logger.info(f"Found company link: {href}")
                    break

            if not company_url:
                self.logger.warning(
                    "No company link found with /company/ in href, assuming not staffing company"  # noqa: E501
                )
                return False

            # Open a new page (tab) in the same browser context
            context = self.bot.page.context
            new_page = context.new_page()
            self.logger.info("Opened new tab for company page")

            # Navigate to company page in the new tab
            new_page.goto(company_url, wait_until="domcontentloaded")
            time.sleep(2)  # Wait for company page to load

            # Get company info from the org-top-card__primary-content div
            company_info_div = new_page.locator(
                'div[class*="org-top-card__primary-content"]'
            )

            if company_info_div.count() == 0:
                self.logger.warning(
                    "Company info div not found, assuming not staffing company"
                )
                return False

            # Get the inner text
            company_info = company_info_div.inner_text()

            if self.bot.page.locator('section[class*="artdeco-card"]').count() > 0:
                company_about = self.bot.page.locator(
                    'section[class*="artdeco-card"]'
                ).first.inner_text()
                company_info += "\n\n" + company_about

            if not company_info or company_info.strip() == "":
                self.logger.warning(
                    "No company info text found, assuming not staffing company"
                )
                return False

            self.logger.info(f"Company info retrieved: {company_info[:200]}...")

            # Call service gateway to check if it's a staffing company
            import requests  # noqa: E402

            from constants import SERVICE_GATEWAY_URL  # noqa: E402
            from services.jwt_token_manager import jwt_token_manager  # noqa: E402

            # Get JWT token for authentication
            token = jwt_token_manager.get_token()
            headers = {"Content-Type": "application/json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            else:
                self.logger.warning("No JWT token available for staffing company check")

            # Call service gateway API
            response = requests.post(
                f"{SERVICE_GATEWAY_URL}/api/company/staff_company",
                json={"company_info": company_info},
                headers=headers,
                timeout=30,
            )

            if response.status_code == 200:
                result = response.json()
                is_staffing = result.get("is_staffing_company", False)
                reasoning = result.get("reasoning", "")

                self.logger.info(
                    f"Staffing company check result: {is_staffing} - {reasoning}"
                )

                if is_staffing:
                    self.send_activity_message(
                        f"**Staffing company detected:** {reasoning}",
                        ActivityType.RESULT,
                    )

                    # Store staffing company to database
                    self._store_staffing_company(company_url, reasoning)
                else:
                    self.send_activity_message(
                        "**Not a staffing company**", ActivityType.RESULT
                    )

                return is_staffing  # noqa: E501
            else:
                self.logger.error(
                    f"Failed to check staffing company: {response.status_code} - {response.text}"  # noqa: E501
                )
                return False

        except Exception as e:
            self.logger.error(f"Error checking if staffing company: {e}")
            return False
        finally:
            # Always close the new page/tab
            if new_page:
                try:
                    self.logger.info("Closing company page tab...")
                    new_page.close()
                except Exception as e:
                    self.logger.error(f"Failed to close company page tab: {e}")

    def _store_staffing_company(self, company_url: str, reasoning: str):
        """
        Store staffing company information to the database.

        Args:
            company_url: The LinkedIn company URL
            reasoning: Why this company is identified as a staffing company
        """
        try:
            import hashlib  # noqa: E402

            import requests  # noqa: E402

            from constants import SERVICE_GATEWAY_URL  # noqa: E402
            from services.jwt_token_manager import jwt_token_manager  # noqa: E402

            # Get company name from current job data
            company_name = self.cur_job_data.get("company_name", "Unknown")

            # Generate ID from company name (lowercase, no spaces, hash)
            company_id = hashlib.md5(company_name.lower().encode()).hexdigest()[:16]

            # Get JWT token for authentication
            token = jwt_token_manager.get_token()
            headers = {"Content-Type": "application/json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            else:
                self.logger.warning(
                    "No JWT token available for storing staffing company"
                )
                return

            # Prepare data
            data = {
                "id": company_id,
                "company_name": company_name,
                "company_website_url": company_url,
                "why_staffing_company": reasoning,
            }

            # Call service gateway API to store the record
            response = requests.post(
                f"{SERVICE_GATEWAY_URL}/api/company/staffing-companies",
                json=data,
                headers=headers,
                timeout=10,
            )

            if response.status_code == 200:
                self.logger.info(
                    f"Successfully stored staffing company: {company_name}"
                )
            elif response.status_code == 409:
                # Conflict - record already exists
                self.logger.info(
                    f"Staffing company already in database: {company_name}"
                )
            else:
                self.logger.warning(
                    "Failed to store staffing company: "
                    f"{response.status_code} - {response.text}"
                )

        except Exception as e:
            # Don't fail the whole process if storing fails
            self.logger.error(f"Error storing staffing company: {e}")

    def _stop_bot_due_to_subscription_limit(self):
        """
        Stop the bot completely when subscription limit is reached
        Similar to StopHuntingAction but without sending additional messages
        """
        try:
            self.logger.info("Stopping bot due to subscription limit")

            # Mark as not running immediately to stop any ongoing operations
            self.bot.is_running = False
            self.bot.status = "stopped"

            # Close browser resources completely
            if self.bot.browser_operator:
                try:
                    self.logger.info("Closing browser operator")
                    self.bot.browser_operator.close()

                    # Brief pause to allow graceful shutdown
                    import time

                    time.sleep(1)

                    self.logger.info("Browser operator closed")
                except Exception as e:
                    self.logger.error(f"Error closing browser: {e}")

            # Clear all bot state
            self.bot.page = None
            self.bot.current_url = ""

            if hasattr(self.bot, "workflow_run_id"):
                self.bot.workflow_run_id = None

            self.logger.info("Bot stopped successfully due to subscription limit")

        except Exception as e:
            self.logger.error(f"Error stopping bot: {e}")
            # Force cleanup on error
            self.bot.is_running = False
            self.bot.status = "error"

    def _upload_screenshot_to_blob(self, screenshot_path: str) -> Optional[str]:
        """
        Upload screenshot to blob storage via service-gateway
        Returns the blob URL if successful, None otherwise
        """
        try:
            from services.jwt_token_manager import jwt_token_manager

            token = jwt_token_manager.get_token()
            if not token:
                self.logger.warning("No JWT token available for screenshot upload")
                return None

            # Read screenshot file
            with open(screenshot_path, "rb") as f:
                files = {"file": (os.path.basename(screenshot_path), f, "image/png")}

                # Upload to blob storage
                response = requests.post(
                    f"{SERVICE_GATEWAY_URL}/api/blob/upload?container=screenshots&folder=failed-jobs",
                    headers={"Authorization": f"Bearer {token}"},
                    files=files,
                    timeout=30,
                )

            if response.status_code == 200:
                response_data = response.json()
                blob_url = response_data.get("blob_url")
                if blob_url:
                    self.logger.info(f"Screenshot uploaded to: {blob_url}")
                    return blob_url
                else:
                    self.logger.error(f"No blob_url in response: {response_data}")
                    return None
            else:
                self.logger.error(
                    f"Failed to upload screenshot: {response.status_code}"
                )
                return None

        except Exception as e:
            self.logger.error(f"Error uploading screenshot: {e}")
            return None

    def _send_mixpanel_failed_application(
        self, error: Exception, screenshot_url: Optional[str]
    ):
        """Send Mixpanel event for failed application via service-gateway"""
        try:
            from services.jwt_token_manager import jwt_token_manager

            token = jwt_token_manager.get_token()
            if not token:
                self.logger.warning("No JWT token available for Mixpanel event")
                return

            # Prepare event properties
            properties = {
                **self.cur_job_data,
                "error": str(error),
                "screenshot_url": screenshot_url,
                "traceback": traceback.format_exc(),
            }

            # Send to service-gateway
            response = requests.post(
                f"{SERVICE_GATEWAY_URL}/api/analytics/mixpanel",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={"event_name": "failed_an_application", "properties": properties},
                timeout=10,
            )

            if response.status_code == 200:
                self.logger.info("Mixpanel event sent successfully")
            else:
                self.logger.error(
                    f"Failed to send Mixpanel event: {response.status_code}"
                )

        except Exception as e:
            self.logger.error(f"Error sending Mixpanel event: {e}")

    def _send_mixpanel_interrupted_application(self, error: Exception):
        """Send Mixpanel event for interrupted application via service-gateway"""
        try:
            from services.jwt_token_manager import jwt_token_manager

            token = jwt_token_manager.get_token()
            if not token:
                self.logger.warning("No JWT token available for Mixpanel event")
                return

            # Prepare event properties (no screenshot for interruptions)
            properties = {
                **self.cur_job_data,
                "error": str(error),
                "reason": "browser_closed",
            }

            # Send to service-gateway
            response = requests.post(
                f"{SERVICE_GATEWAY_URL}/api/analytics/mixpanel",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={
                    "event_name": "interrupted_an_application",
                    "properties": properties,
                },
                timeout=10,
            )

            if response.status_code == 200:
                self.logger.info("Mixpanel interrupted event sent successfully")
            else:
                self.logger.error(
                    f"Failed to send Mixpanel event: {response.status_code}"
                )

        except Exception as e:
            self.logger.error(f"Error sending Mixpanel interrupted event: {e}")

    def _send_slack_failed_notification(
        self, error: Exception, screenshot_url: Optional[str]
    ):
        """Send Slack notification for failed application via service-gateway"""
        try:
            from services.jwt_token_manager import jwt_token_manager

            token = jwt_token_manager.get_token()
            if not token:
                self.logger.warning("No JWT token available for Slack notification")
                return

            # Format job info
            company_name = self.cur_job_data.get("company_name", "Unknown")
            job_title = self.cur_job_data.get("job_title", "Unknown")
            job_url = self.cur_job_data.get("application_url", "")

            # Build Slack blocks for rich formatting
            blocks = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"Failed Application: {company_name}",
                    },
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Job Title:*\n{job_title}"},
                        {"type": "mrkdwn", "text": f"*Company:*\n{company_name}"},
                    ],
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Error:*\n```{str(error)}```"},
                },
            ]

            # Add job URL if available
            if job_url:
                blocks.append(
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Job URL:*\n<{job_url}|View Job Posting>",
                        },
                    }
                )

            # Add screenshot if available (must be a valid URL starting with http)
            if screenshot_url and screenshot_url.startswith(("http://", "https://")):
                self.logger.info(
                    f"Adding screenshot to Slack notification: {screenshot_url}"
                )
                blocks.append(
                    {
                        "type": "image",
                        "image_url": screenshot_url,
                        "alt_text": "Screenshot of failed application",
                    }
                )
            else:
                if screenshot_url:
                    self.logger.warning(
                        f"Invalid screenshot URL (not a valid http/https URL): {screenshot_url}"
                    )
                else:
                    self.logger.warning(
                        "No screenshot URL available for Slack notification"
                    )

            # Add traceback
            trace_text = traceback.format_exc()[:2000]  # Slack has limits
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Traceback:*\n```{trace_text}```",
                    },
                }
            )

            # Send to service-gateway
            response = requests.post(
                f"{SERVICE_GATEWAY_URL}/api/analytics/slack",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={
                    "channel": "failed_jobs",
                    "text": f"Failed to apply to {company_name} - {job_title}: {str(error)}",
                    "blocks": blocks,
                },
                timeout=10,
            )

            if response.status_code == 200:
                self.logger.info("Slack notification sent successfully")
            else:
                self.logger.error(
                    f"Failed to send Slack notification: {response.status_code}"
                )

        except Exception as e:
            self.logger.error(f"Error sending Slack notification: {e}")
