"""
Application History Tracker v2 - Database-driven application tracking
Same interface as v1, just uses Supabase instead of JSON file
"""

import logging
from collections import OrderedDict
from typing import Optional

from services.supabase_client import supabase_client
from shared.infinite_hunt_metadata import get_metadata_service

logger = logging.getLogger(__name__)


class ApplicationHistoryTracker:
    def __init__(self, user_id: str, workflow_run_id: Optional[str] = None):
        self.user_id = user_id
        self.workflow_run_id = workflow_run_id
        self.application_history: OrderedDict = self.load_application_history()
        self.callbacks = []
        # Queue to track updates: {app_history_id: {attr_name: attr_value, ...}}
        self.update_queue = {}
        self.reset_application_history()

    def set_workflow_run_id(self, workflow_run_id: str):
        """Set the workflow run ID for metadata tracking."""
        self.workflow_run_id = workflow_run_id

    def reset_application_history(self):
        self.cur_recording_app_history_id = None

    def get_update_queue_status(self):
        """Get current status of the update queue"""
        return {
            "queue_size": len(self.update_queue),
            "pending_updates": {
                app_id: list(updates.keys())
                for app_id, updates in self.update_queue.items()
            },
        }

    def update_application(self, app_history_id: str, attr_name: str, attr_value: any):
        # Map attribute names for database compatibility
        attr_mapping = {
            "application_history_id": "id",
            # Add other mappings as needed
        }

        # Get the database field name (use mapping if exists, otherwise use as-is)
        db_field_name = attr_mapping.get(attr_name, attr_name)

        # Update local cache (same as v1)
        if app_history_id not in self.application_history:
            self.application_history[app_history_id] = {}

        # Check if the value is actually different before updating
        current_value = self.application_history[app_history_id].get(db_field_name)
        if current_value != attr_value:
            # Update local cache with database field name
            self.application_history[app_history_id].update({db_field_name: attr_value})

            # Add to update queue only if value changed (use database field name)
            if app_history_id not in self.update_queue:
                self.update_queue[app_history_id] = {}
            self.update_queue[app_history_id][db_field_name] = attr_value

            logger.debug(
                f"Queued update for {app_history_id}: {attr_name} -> "
                f"{db_field_name} = {attr_value} (was: {current_value})"
            )

            # Update metadata service when status changes
            if db_field_name == "status":
                self._update_metadata_stats(attr_value)
        else:
            logger.debug(
                f"Skipped update for {app_history_id}: {attr_name} -> "
                f"{db_field_name} = {attr_value} (no change)"
            )

        # Sort by application_datetime if that's what was updated
        if db_field_name == "application_datetime":
            self._sort_by_datetime()

    def _sort_by_datetime(self):
        """Sort application history by application_datetime in descending order."""

        def safe_datetime_key(item):
            dt_value = item[1].get("application_datetime", "")
            if isinstance(dt_value, (int, float)):
                return dt_value
            elif isinstance(dt_value, str) and dt_value:
                try:
                    # Try to parse as ISO string or convert to float
                    from datetime import datetime  # noqa: E402

                    if "T" in dt_value or "-" in dt_value:
                        return datetime.fromisoformat(
                            dt_value.replace("Z", "+00:00")
                        ).timestamp()
                    else:
                        return float(dt_value)
                except Exception:
                    return 0
            else:
                return 0

        self.application_history = OrderedDict(
            sorted(
                self.application_history.items(),
                key=safe_datetime_key,
                reverse=True,
            )
        )

    def _update_metadata_stats(self, status: str):
        """
        Update the infinite hunt metadata service with job stats.

        Args:
            status: Application status (QUEUED, SKIPPED, SUBMITTED, etc.)
        """
        try:
            metadata_service = get_metadata_service()
            status_lower = status.lower()

            if status_lower == "queued":
                metadata_service.increment_queued(self.workflow_run_id)
            elif status_lower == "skipped":
                metadata_service.increment_skipped(self.workflow_run_id)
            elif status_lower in ("submitted", "applied"):
                metadata_service.increment_submitted(self.workflow_run_id)
            elif status_lower == "failed":
                metadata_service.increment_failed(self.workflow_run_id)
        except Exception as e:
            logger.debug(f"Failed to update metadata stats: {e}")

    def load_application_history(self):
        try:
            # Use the supabase client to get application history
            # The method doesn't exist yet, so let's implement a direct API call
            response = supabase_client._make_request("GET", "/api/application-history/")

            if response.status_code == 200:
                data = response.json()
                applications = data.get("applications", [])

                # Convert to OrderedDict like v1
                history = OrderedDict()
                for record in applications:
                    # Use 'id' as the key since that's the primary key
                    app_history_id = record.get("id")
                    if app_history_id:
                        # Use ID directly - now all IDs are generated with UUID format (with dashes)  # noqa: E501
                        history[app_history_id] = record

                # Sort by application_datetime (desc)
                def safe_datetime_key(item):
                    dt_value = item[1].get("application_datetime", "")
                    if isinstance(dt_value, (int, float)):
                        return dt_value
                    elif isinstance(dt_value, str) and dt_value:
                        try:
                            # Try to parse as ISO string or convert to float
                            from datetime import datetime  # noqa: E402

                            if "T" in dt_value or "-" in dt_value:
                                return datetime.fromisoformat(
                                    dt_value.replace("Z", "+00:00")
                                ).timestamp()
                            else:
                                return float(dt_value)
                        except Exception:
                            return 0
                    else:
                        return 0

                history = OrderedDict(
                    sorted(
                        history.items(),
                        key=safe_datetime_key,
                        reverse=True,
                    )
                )
                return history
            else:
                logger.warning(
                    f"Failed to load application history: HTTP {response.status_code}"
                )
                return OrderedDict()

        except Exception as e:
            logger.error(f"Error loading application history: {e}")
            return OrderedDict()

    def process_update_queue(self):
        """Process queued updates by calling update_application_history for each"""
        if not self.update_queue:
            logger.debug("No updates in queue to process")
            return

        try:
            logger.info(f"Processing {len(self.update_queue)} queued updates...")

            for app_history_id, updates in self.update_queue.items():
                logger.info(
                    f"Updating {app_history_id} with attributes: {list(updates.keys())}"
                )

                # Call update_application_history with only the changed attributes
                success = supabase_client.update_application_history(
                    app_history_id, updates
                )

                if not success:
                    logger.error(f"Failed to update application {app_history_id}")
                else:
                    logger.info(f"Successfully updated application {app_history_id}")

            # Clear the queue after processing
            self.update_queue.clear()
            logger.info("Update queue processed and cleared")
            self.notify_callbacks()

        except Exception as e:
            logger.error(f"Error processing update queue: {e}")
            import traceback  # noqa: E402

            logger.debug(f"Update queue error traceback: {traceback.format_exc()}")

    def deduplicate_questions_and_answers(self, qna_list):
        """
        Deduplicate questions and answers based on question text + question_type

        Args:
            qna_list: List of Q&A dictionaries

        Returns:
            Deduplicated list, keeping the last occurrence of each unique question+type
        """
        if not qna_list:
            return qna_list

        seen = {}

        for item in qna_list:
            # Create unique key from question text and type
            question = item.get("question", "").strip().lower()
            question_type = item.get("question_type", "").strip().lower()
            key = f"{question}|{question_type}"

            # Keep track of the item (this will overwrite previous occurrences)
            seen[key] = item

        # Convert back to list, preserving the last occurrence of each unique item
        deduplicated = list(seen.values())

        logger.debug(f"Deduplicated Q&A: {len(qna_list)} -> {len(deduplicated)} items")
        return deduplicated

    def sync_application_history(self):
        """
        Sync application history by processing queued updates
        """
        try:
            # Process any queued updates (partial updates)
            if self.update_queue:
                logger.info("Processing queued updates...")
                self.process_update_queue()
            else:
                logger.debug("No queued updates to process")

            logger.info("Application history sync completed")
            self.notify_callbacks()

        except Exception as e:
            logger.error(f"Error syncing application history: {e}")
            import traceback  # noqa: E402

            logger.debug(f"Sync error traceback: {traceback.format_exc()}")

    def register_callback(self, callback):
        self.callbacks.append(callback)

    def notify_callbacks(self):
        for callback in self.callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"Error calling callback: {e}")

    def create_application_history(self) -> str:
        """
        Create a new application history record

        Args:
            application_data: Dictionary containing application information

        Returns:
            str: The generated application history ID

        Raises:
            SubscriptionLimitException: When user has reached their application limit
        """
        try:
            # Set default values
            create_data = {
                "id": self.cur_recording_app_history_id,
                "user_id": self.user_id,
                "status": "started",  # Default status when creating a new record
                "ats_score": 0,
                "ats_alignments": [],
                "ats_keyword_to_add_to_resume": [],
                "optimized_ats_alignments": [],
                "criteria_alignment": [],
                "resume_id": "",
                "hiring_team": {},
                "num_applicants": 0,
                "pos_context": "",
                "salary_range": None,
                "questions_and_answers": [],
                **self.update_queue.get(
                    self.cur_recording_app_history_id, {}
                ),  # Override defaults with provided data
            }
            # Note: application_datetime should only be set when status
            # becomes 'applied'
            # It will be set by the bot when the application is actually submitted

            # STEP 1: Create or update job description first (if job_description_id provided)
            job_description_id = create_data.get("job_description_id")
            if job_description_id:
                # Extract job description fields from create_data
                # Note: salary_range can be str, list, or None - service gateway accepts all formats
                job_desc_data = {
                    "id": job_description_id,
                    "application_url": create_data.get("application_url", ""),
                    "linkedin_job_id": create_data.get("linkedin_job_id"),
                    "company_name": create_data.get("company_name"),
                    "location": create_data.get("location"),
                    "job_title": create_data.get("job_title"),
                    "post_time": create_data.get("post_time"),
                    "hiring_team": create_data.get("hiring_team", {}),
                    "num_applicants": create_data.get("num_applicants", 0),
                    "pos_context": create_data.get("pos_context", ""),
                    "salary_range": create_data.get("salary_range"),
                }

                # Create/update job description (upsert)
                job_desc_result = supabase_client.create_or_update_job_description(
                    job_desc_data
                )

                if job_desc_result:
                    logger.info(
                        f"Job description created/updated: {job_description_id}"
                    )
                else:
                    logger.error(
                        f"Failed to create/update job description: {job_description_id}"
                    )
                    # Return False - job description creation MUST succeed to satisfy foreign key
                    return ""

            # STEP 2: Create application history record in database
            success = supabase_client.create_application_history(create_data)

            if success:
                # Add to local cache
                self.application_history[
                    self.cur_recording_app_history_id
                ] = create_data

                # Re-sort by application_datetime
                def safe_datetime_key(item):
                    dt_value = item[1].get("application_datetime", "")
                    if isinstance(dt_value, (int, float)):
                        return dt_value
                    elif isinstance(dt_value, str) and dt_value:
                        try:
                            from datetime import datetime  # noqa: E402

                            if "T" in dt_value or "-" in dt_value:
                                return datetime.fromisoformat(
                                    dt_value.replace("Z", "+00:00")
                                ).timestamp()
                            else:
                                return float(dt_value)
                        except Exception:
                            return 0
                    else:
                        return 0

                self.application_history = OrderedDict(
                    sorted(
                        self.application_history.items(),
                        key=safe_datetime_key,
                        reverse=True,
                    )
                )

                logger.info(
                    f"Created application history record: {self.cur_recording_app_history_id}"  # noqa: E501
                )
                self.notify_callbacks()
                return self.cur_recording_app_history_id
            else:
                logger.warning(
                    f"The job already exists in the database. Syncing it: {self.cur_recording_app_history_id}"  # noqa: E501
                )
                update_success = supabase_client.update_application_history(
                    self.cur_recording_app_history_id,
                    self.update_queue.get(self.cur_recording_app_history_id, {}),
                )
                if not update_success:
                    logger.error(
                        f"Failed to sync application history record: {self.cur_recording_app_history_id}"  # noqa: E501
                    )
                logger.info(
                    f"Synced application history record: {self.cur_recording_app_history_id}"  # noqa: E501
                )
                self.notify_callbacks()
                return self.cur_recording_app_history_id

        except Exception as e:
            # Check if it's a limit exception and propagate it
            from exceptions import DailyLimitException  # noqa: E402
            from exceptions import SubscriptionLimitException  # noqa: E402

            if isinstance(e, SubscriptionLimitException):
                logger.warning(f"Subscription limit reached: {e.message}")
                raise  # Propagate the exception to stop hunting
            elif isinstance(e, DailyLimitException):
                logger.warning(f"Daily limit reached: {e.message}")
                raise  # Propagate the exception to stop hunting
            logger.error(f"Error creating application history: {e}")
            raise

    def get_job_item_from_history(self, app_history_id: str):
        # For v2, first check local cache (like v1), then fallback to database
        if app_history_id in self.application_history:
            return self.application_history[app_history_id]

        # If not in local cache, try to get from database
        try:
            record = supabase_client.get_application_history_by_id(app_history_id)
            if record:
                return record
            return {}

        except Exception as e:
            logger.error(f"Error getting job item {app_history_id}: {e}")
            return {}
