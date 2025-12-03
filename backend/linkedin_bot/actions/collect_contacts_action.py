#!/usr/bin/env python3
"""
Collect Contacts Action for LinkedIn Bot

This action collects hiring manager contacts from LinkedIn job
applications. It takes a list of application history records and
navigates to each application URL to extract contact information.
"""

import logging
import time
import uuid  # noqa: E402
from typing import Any, Union  # noqa: E402
from urllib.parse import urlparse, urlunparse  # noqa: E402

import requests  # noqa: E402

from browser.browser_operator import BrowserOperator  # noqa: E402
from config import (  # noqa: E402
    MAX_PEERS_PER_APPLICATION,
    MAX_RECRUITERS_PER_APPLICATION,
)
from constants import SERVICE_GATEWAY_URL  # noqa: E402
from services.jwt_token_manager import jwt_token_manager  # noqa: E402
from services.supabase_client import supabase_client  # noqa: E402
from shared.models.job_description import HiringTeam  # noqa: E402

from .base_action import BaseAction  # noqa: E402

logger = logging.getLogger(__name__)


class CollectContactsAction(BaseAction):
    """
    Action to collect contacts from LinkedIn job applications.  # noqa: E402

    Takes application history records with linkedin_job_id and
    navigates to each application URL to collect hiring manager/
    recruiter contacts.
    """

    def __init__(self, bot_instance, existing_contacts: list[dict] = None):
        """
        Initialize the collect contacts action

        Args:
            bot_instance: Bot instance
            existing_contacts: List of already collected contacts from DB  # noqa: E402
        """
        super().__init__(bot_instance)
        self.browser_operator: BrowserOperator | None = None
        self.page = None
        # Cache for workflow_run_id -> resume_text mapping
        self.resume_cache: dict[str, str] = {}
        # Store existing contacts indexed by normalized profile URL
        self.existing_contacts_map: dict[str, dict] = {}
        if existing_contacts:
            for contact in existing_contacts:
                normalized_url = self._normalize_url(contact.get("linkedin_url", ""))
                if normalized_url:
                    self.existing_contacts_map[normalized_url] = contact

    def _require_browser_operator(self) -> BrowserOperator:
        """Return an active browser operator or raise an error."""
        if self.browser_operator is None:
            raise RuntimeError("Browser operator is not initialized")
        return self.browser_operator

    @property
    def action_name(self) -> str:
        """Return the name of this action"""
        return "collect_contacts"

    def execute(self, application_history_list: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Execute contact collection from application history records.  # noqa: E402

        Args:
            application_history_list: List of application history
                records with linkedin_job_id

        Returns:
            Dict containing success status and collected contacts
        """
        try:
            num_apps = len(application_history_list)
            self.logger.info(
                f"Starting contact collection for {num_apps} " f"applications"
            )

            # Validate input
            if not application_history_list:
                error_msg = "No application history records provided"
                return {"success": False, "error": error_msg, "contacts": []}

            # Filter records that have linkedin_job_id and
            # application_url
            valid_records = [
                record
                for record in application_history_list
                if (record.get("linkedin_job_id") and record.get("application_url"))
            ]

            if not valid_records:
                error_msg = (
                    "No valid records with linkedin_job_id " "and application_url found"
                )
                return {"success": False, "error": error_msg, "contacts": []}

            num_valid = len(valid_records)
            self.logger.info(f"Found {num_valid} valid applications to process")

            # Initialize browser
            self._init_browser()
            browser = self._require_browser_operator()

            # Process each application
            collected_contacts = []
            for idx, record in enumerate(valid_records, 1):
                try:
                    job_title = record.get("job_title", "Unknown")
                    company = record.get("company_name", "Unknown")
                    self.logger.info(
                        f"Processing application {idx}/"
                        f"{len(valid_records)}: "
                        f"{job_title} at {company}"
                    )

                    # Navigate to application URL
                    application_url = record.get("application_url")
                    browser.navigate_to(application_url)

                    # Go to company page
                    top_card = 'div[class*="job-details-jobs-unified-'
                    top_card += 'top-card__container"]'
                    company_link = self.page.locator(top_card).locator("a").first
                    browser.click_with_op(company_link)

                    # Click on people tab
                    people_tab = self.page.locator(
                        'li[class*="org-page-navigation__item"]'
                    ).filter(has_text="people")
                    browser.click_with_op(people_tab)

                    # Wait for search bar to load
                    time.sleep(1)

                    # Prepare position info for AI filtering
                    position_info = {
                        "job_title": record.get("job_title", ""),
                        "company_name": record.get("company_name", ""),
                        "job_description": record.get("pos_context", ""),
                        "location": record.get("location", ""),
                    }

                    # Collect and filter contacts for different roles
                    all_contacts_with_source = []

                    # 1. Collect recruiters
                    recruiter_contacts = self._collect_contacts_by_role(
                        "recruiter", max_iterations=10
                    )
                    if (
                        recruiter_contacts
                        and len(recruiter_contacts) > MAX_RECRUITERS_PER_APPLICATION
                    ):
                        filtered_recruiters = self._filter_contacts_by_ai(
                            contacts=recruiter_contacts,
                            position_info=position_info,
                            target_role="recruiter",
                            max_reachout_count=MAX_RECRUITERS_PER_APPLICATION,
                        )
                        # Mark these as recruiter category
                        for contact in filtered_recruiters:
                            contact["category"] = "recruiter"
                        all_contacts_with_source.extend(filtered_recruiters)

                    time.sleep(2)

                    # 2. Collect Peers
                    target_role = position_info.get("job_title")
                    peers_contacts = self._collect_contacts_by_role(
                        target_role, max_iterations=10
                    )
                    if (
                        peers_contacts
                        and len(peers_contacts) > MAX_PEERS_PER_APPLICATION
                    ):
                        filtered_peers = self._filter_contacts_by_ai(
                            contacts=peers_contacts,
                            position_info=position_info,
                            target_role=target_role,
                            max_reachout_count=MAX_PEERS_PER_APPLICATION,
                        )
                        # Mark these as peer category
                        for contact in filtered_peers:
                            contact["category"] = "peer"
                        all_contacts_with_source.extend(filtered_peers)

                    time.sleep(2)

                    # if no contacts collected, remove filters and get all
                    if not all_contacts_with_source:
                        all_contacts = self._collect_contacts_by_role(
                            "", max_iterations=10
                        )
                        max_all = (
                            MAX_PEERS_PER_APPLICATION + MAX_RECRUITERS_PER_APPLICATION
                        )
                        if all_contacts and len(all_contacts) > max_all:
                            max_count = (
                                MAX_PEERS_PER_APPLICATION
                                + MAX_RECRUITERS_PER_APPLICATION
                            )
                            filtered_all_contacts = self._filter_contacts_by_ai(
                                contacts=all_contacts,
                                position_info=position_info,
                                target_role="",
                                max_reachout_count=max_count,
                            )
                            # Mark as peer by default
                            for contact in filtered_all_contacts:
                                contact["category"] = "peer"
                            all_contacts_with_source.extend(filtered_all_contacts)
                            # Add remaining as peer
                            for contact in all_contacts:
                                contact["category"] = "peer"
                            all_contacts_with_source.extend(all_contacts)

                    # Add hiring team contact if available
                    contacts_with_category = self._add_hiring_team_contact(
                        all_contacts_with_source, record.get("hiring_team", {})
                    )

                    # enter each contact's url to collect more information
                    # and make deep analysis of the contact
                    for contact in contacts_with_category:
                        try:
                            profile_url = contact["profile_url"]

                            # Normalize URL and check if already collected
                            normalized_url = self._normalize_url(profile_url)
                            if normalized_url in self.existing_contacts_map:
                                existing = self.existing_contacts_map[normalized_url]
                                self.logger.info(
                                    f"Skipping {contact.get('name')} - "
                                    "already collected (ID: "
                                    f"{existing.get('id')})"
                                )
                                # Add existing contact to results
                                collected_contacts.append(existing)
                                continue

                            # Update contact with normalized URL
                            contact["profile_url"] = normalized_url

                            browser.navigate_to(normalized_url)

                            # Collect all profile information
                            profile_data = self._extract_profile_data(contact)

                            # Get user resume for this record's
                            # workflow run
                            user_resume_text = self._get_resume_for_record(record)

                            # Enrich contact with AI - pass raw text
                            enriched_data = self._enrich_contact_with_ai(
                                name=contact.get("name", "Unknown"),
                                current_role=profile_data["subtitle"],
                                profile_url=contact.get("profile_url", ""),
                                about_text=profile_data["about"],
                                work_history_text=profile_data["work_history"],
                                education_text=profile_data["education"],
                                activities_text=profile_data["activities"],
                                job_title=record.get("position_title", ""),
                                company=record.get("company_name", ""),
                                job_description=position_info.get(
                                    "job_description", ""
                                ),
                                user_resume_text=user_resume_text,
                            )

                            # Create enriched contact with snake_case
                            # keys
                            # Generate UUID from normalized profile URL
                            contact_id = self._generate_contact_id(normalized_url)

                            # Upload profile picture to blob storage
                            linkedin_image_url = profile_data["image_url"]
                            blob_image_url = None
                            if linkedin_image_url:
                                self.logger.info(
                                    "Uploading profile pic for "
                                    f"{contact.get('name')}"
                                )
                                blob_image_url = self._upload_profile_pic_to_blob(
                                    linkedin_image_url, contact_id
                                )

                            # Use blob URL if upload succeeded,
                            # otherwise keep original
                            # (will fallback to avatar)
                            final_image_url = blob_image_url or linkedin_image_url

                            enriched_contact = {
                                "id": contact_id,
                                "application_history_id": (record.get("id")),
                                "job_title": (enriched_data.get("job_title", "")),
                                "company": (record.get("company_name", "")),
                                "name": contact.get("name", "Unknown"),
                                "target_role": record.get("job_title", ""),
                                "profile_picture_url": final_image_url,
                                "linkedin_url": normalized_url,
                                "connection_degree": (
                                    profile_data["connection_degree"]
                                ),
                                "category": (contact.get("category", "peer")),
                                "about": enriched_data.get("about", ""),
                                "work_history": (enriched_data.get("work_history", [])),
                                "education": (enriched_data.get("education", [])),
                                "recent_activity": (
                                    enriched_data.get("recent_activity", [])
                                ),
                                "why_outreach": (enriched_data.get("why_outreach", "")),
                                "personalized_outreach_tips": (
                                    enriched_data.get("personalized_outreach_tips", [])
                                ),
                                "draft_message": (
                                    enriched_data.get("draft_message", "")
                                ),
                                "status": "collected",
                                "collected_at": time.strftime(
                                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                                ),
                            }

                            # Save contact to database immediately
                            saved_contact = self._save_contact_to_db(enriched_contact)
                            if saved_contact:
                                collected_contacts.append(saved_contact)
                                self.logger.info(
                                    f"Saved contact {contact.get('name')} "
                                    "to database"
                                )

                                # Append contact ID to application history
                                self._append_contact_to_application(
                                    record.get("id"), contact_id
                                )
                            else:
                                # Still add to list even if save fails
                                collected_contacts.append(enriched_contact)
                                self.logger.warning(
                                    "Failed to save contact "
                                    f"{contact.get('name')} to database, "
                                    "added to memory only"
                                )

                        except Exception as e:
                            self.logger.warning(
                                "Error enriching contact " f"{contact.get('name')}: {e}"
                            )
                            continue

                    self.logger.info(
                        f"Collected {len(collected_contacts)} enriched "
                        f"contacts for {record.get('company_name')}"
                    )

                    # Mark contact collection as complete for this job
                    self._mark_collection_complete(record.get("id"))

                except Exception as e:
                    record_id = record.get("id", "Unknown")
                    self.logger.error(f"Error processing application {record_id}: {e}")
                    continue

            num_processed = len(valid_records)
            num_contacts = len(collected_contacts)
            self.logger.info(
                "Contact collection completed. "
                f"Processed {num_processed} applications, "
                f"collected {num_contacts} contacts"
            )

            return {
                "success": True,
                "contacts": collected_contacts,
                "processed_count": len(valid_records),
                "message": (
                    f"Processed {len(valid_records)} applications, "
                    f"collected {num_contacts} contacts"
                ),
            }

        except Exception as e:
            error_msg = f"Error during contact collection: {e}"
            self.logger.error(error_msg)
            return {"success": False, "error": error_msg, "contacts": []}
        finally:
            # Clean up browser resources
            self._cleanup_browser()

    @staticmethod
    def _normalize_url(url: str) -> str:
        """
        Normalize URL by removing query parameters and fragments.

        Args:
            url: Original URL

        Returns:
            Normalized URL without query params
        """
        if not url:
            return ""

        try:
            parsed = urlparse(url)
            # Remove query params and fragment
            normalized = urlunparse(
                (
                    parsed.scheme,
                    parsed.netloc,
                    parsed.path,
                    "",  # params
                    "",  # query
                    "",  # fragment
                )
            )
            return normalized.rstrip("/")
        except Exception as e:
            logger.warning(f"Failed to normalize URL {url}: {e}")
            return url.split("?")[0].split("#")[0].rstrip("/")

    @staticmethod
    def _generate_contact_id(profile_url: str) -> str:
        """
        Generate deterministic UUID from normalized profile URL.  # noqa: E402

        Args:
            profile_url: LinkedIn profile URL

        Returns:
            UUID string generated from URL  # noqa: E402
        """
        normalized_url = CollectContactsAction._normalize_url(profile_url)
        # Generate UUID5 from URL (deterministic)
        contact_uuid = uuid.uuid5(uuid.NAMESPACE_URL, normalized_url)
        return str(contact_uuid)

    def _init_browser(self):
        """Initialize browser operator"""
        try:
            self.logger.info("Launching browser for contact collection...")

            browser = BrowserOperator(
                headless=False,
            )

            # Set bot instance reference for stop signal detection
            browser.set_bot_instance(self.bot)

            # Start browser and get page
            self.page = browser.start()
            self.browser_operator = browser

            self.logger.info("Browser initialized successfully")

        except Exception as e:
            raise Exception(f"Failed to initialize browser: {e}")

    def _add_hiring_team_contact(
        self,
        contacts: list[dict[str, Any]],
        hiring_team: Union[dict[str, Any], HiringTeam, None],
    ) -> list[dict[str, Any]]:
        """
        Add hiring team contact to the list if not already present.

        The hiring_team contact is marked as "hiring_manager" unless
        their title contains "recruiter" keywords, in which case they
        remain as "recruiter".

        Args:
            contacts: List of contact dictionaries with categories
            hiring_team: Hiring team data from application_history  # noqa: E402

        Returns:
            List of contacts with hiring team contact added
        """
        if not hiring_team:
            return contacts

        # Convert HiringTeam model to dict if needed
        if isinstance(hiring_team, HiringTeam):
            hiring_team_dict = hiring_team.model_dump()
        elif isinstance(hiring_team, dict):
            hiring_team_dict = hiring_team
        else:
            return contacts

        hiring_team_url = hiring_team_dict.get("linkedin_url", "")
        if not hiring_team_url:
            return contacts

        # Normalize URL for comparison
        normalized_hiring_url = hiring_team_url.split("?")[0].strip()

        # Check if hiring team contact is already in the list
        existing_contact = None
        for contact in contacts:
            contact_url = contact.get("profile_url", "")
            normalized_contact_url = contact_url.split("?")[0].strip()
            if normalized_contact_url == normalized_hiring_url:
                existing_contact = contact
                break

        if existing_contact:
            # If already exists and is a recruiter, keep as recruiter
            if existing_contact.get("category") == "recruiter":
                self.logger.info(
                    f"{existing_contact.get('name')} from hiring_team "  # noqa: E402
                    "is already marked as recruiter, keeping category"
                )
            else:
                # Override to hiring_manager if not recruiter
                existing_contact["category"] = "hiring_manager"
                self.logger.info(
                    f"{existing_contact.get('name')} updated to "
                    f"hiring_manager (from hiring_team)"  # noqa: E402
                )
        else:
            # Add as new contact
            about_text = hiring_team_dict.get("about_text", "").lower()
            recruiter_keywords = [
                "recruiter",
                "talent acquisition",
                "talent partner",
                "hiring specialist",
            ]
            is_recruiter = any(keyword in about_text for keyword in recruiter_keywords)

            category = "recruiter" if is_recruiter else "hiring_manager"

            new_contact = {
                "name": hiring_team_dict.get("name", "Unknown"),
                "profile_url": hiring_team_url,
                "description": about_text,
                "category": category,
            }
            contacts.append(new_contact)
            self.logger.info(
                f"Added {new_contact['name']} from hiring_team "
                f"as {category}"  # noqa: E402
            )

        return contacts

    def _get_resume_for_record(self, record: dict[str, Any]) -> str:
        """
        Get resume text for a specific record's workflow run.
        Uses cache to avoid loading same resume multiple times.

        Args:
            record: Application history record

        Returns:
            Resume text string
        """
        user_id = record.get("user_id")
        workflow_run_id = record.get("workflow_run_id")

        if not user_id or not workflow_run_id:
            self.logger.debug(
                "No user_id or workflow_run_id in record, " "skipping resume load"
            )
            return ""

        # Check cache first
        cache_key = f"{user_id}_{workflow_run_id}"
        if cache_key in self.resume_cache:
            self.logger.debug(
                f"Using cached resume for workflow_run_id: " f"{workflow_run_id}"
            )
            return self.resume_cache[cache_key]

        # Load from config_reader
        try:
            from shared.config_reader import ConfigReader  # noqa: E402

            self.logger.info(
                f"Loading resume data for user {user_id}, "
                f"workflow_run_id: {workflow_run_id}"
            )
            config_reader = ConfigReader(
                user_id=user_id, workflow_run_id=workflow_run_id
            )
            config_reader.load_configuration()

            # Get resume text
            resume_text = ""
            if isinstance(config_reader.profile.resume, dict):
                # Resume is a dictionary, convert to text
                resume_text = str(config_reader.profile.resume)
            elif isinstance(config_reader.profile.resume, str):
                resume_text = config_reader.profile.resume

            # Cache the result
            self.resume_cache[cache_key] = resume_text

            if resume_text:
                self.logger.info(
                    f"Loaded and cached resume data " f"(length: {len(resume_text)})"
                )

            return resume_text

        except Exception as e:
            self.logger.warning(
                f"Failed to load resume for workflow_run_id " f"{workflow_run_id}: {e}"
            )
            # Cache empty string to avoid retrying
            self.resume_cache[cache_key] = ""
            return ""

    def _maybe_clear_all_filters(self):
        """Clear all search filters if the clear button exists"""
        try:
            browser = self._require_browser_operator()
            clear_all_button = self.page.locator("li[class*=inline]").locator(
                "button[class*=artdeco-button]"
            )
            if clear_all_button.count() > 0:
                self.logger.info("Clearing previous search filters...")
                browser.click_with_op(clear_all_button.first)
                time.sleep(1)
        except Exception as e:
            self.logger.warning(f"Failed to clear filters: {e}")

    def _collect_contacts_by_role(
        self, role_keyword: str, max_iterations: int = 10
    ) -> list[dict[str, Any]]:
        """
        Collect contacts by searching for a specific role.

        Args:
            role_keyword: The role to search for (e.g., "recruiter", "hiring manager")
            max_iterations: Maximum number of times to click "show more results"

        Returns:
            List of collected contacts with name, description, and profile URL
        """
        try:
            browser = self._require_browser_operator()
            self.logger.info(f"Collecting contacts for role: {role_keyword}")

            # Clear any previous filters before searching
            self._maybe_clear_all_filters()

            # Type in the role in search bar
            people_search_bar = self.page.locator("textarea#people-search-keywords")
            browser.scroll_into_view_with_op(people_search_bar, sleep_after=5.0)
            browser.fill_with_op(people_search_bar, role_keyword)
            browser.op(lambda: people_search_bar.press("Enter"))

            # Wait a bit for results to load
            time.sleep(10)

            # Scroll to load more results
            browser.scroll_slowly_to_bottom()

            # Click "show more results" button repeatedly
            iterations = 0
            while iterations < max_iterations:
                show_more_button = self.page.locator(
                    "span[class*=artdeco-button__text]"
                ).filter(has_text="show more results")

                if show_more_button.count() == 0:
                    break

                browser.click_with_op(show_more_button)
                time.sleep(0.1)
                browser.scroll_slowly_to_bottom()
                iterations += 1

            # Collect all contact cards
            all_contact_cards = self.page.locator(
                "li[class*=org-people-profile-card__profile-card-spacing]"
            ).all()

            collected_contacts = []
            for card in all_contact_cards:
                try:
                    # Scroll card into view to ensure it's visible
                    # and fully loaded
                    browser.scroll_into_view_with_op(card, sleep_after=0.1)

                    contact_name = card.locator(
                        "div[class*=artdeco-entity-lockup__title]"
                    ).inner_text()
                    contact_description = card.locator(
                        "div[class*=artdeco-entity-lockup__subtitle]"
                    ).inner_text()
                    contact_profile_url = card.locator("a").first.get_attribute("href")

                    collected_contacts.append(
                        {
                            "name": contact_name,
                            "description": contact_description,
                            "profile_url": contact_profile_url,
                        }
                    )
                except Exception as e:
                    self.logger.warning(f"Failed to extract contact info: {e}")
                    continue

            self.logger.info(
                f"Collected {len(collected_contacts)} contacts for role: {role_keyword}"
            )
            return collected_contacts

        except Exception as e:
            self.logger.error(f"Error collecting contacts for role {role_keyword}: {e}")
            return []

    def _filter_contacts_by_ai(
        self,
        contacts: list[dict[str, Any]],
        position_info: dict[str, Any],
        target_role: str,
        max_reachout_count: int = 3,
    ) -> list[dict[str, Any]]:
        """
        Filter contacts using AI through service-gateway.

        Args:
            contacts: List of collected contacts
            position_info: Job position information
            target_role: Target contact role (e.g., "recruiter", "hiring manager")

        Returns:
            Filtered list of contacts
        """
        try:
            self.logger.info(
                f"Filtering {len(contacts)} contacts by AI for role: {target_role}"
            )

            # Get JWT token for authentication
            token = jwt_token_manager.get_token()
            headers = {}
            if token:
                headers["Authorization"] = f"Bearer {token}"
                self.logger.debug(f"Using JWT token: {token[:20]}...")
            else:
                self.logger.warning("No JWT token available for contact filtering")

            # Call service-gateway AI endpoint
            response = requests.post(
                f"{SERVICE_GATEWAY_URL}/api/contacts/filter",
                json={
                    "contacts": contacts,
                    "position_info": position_info,
                    "target_role": target_role,
                    "max_reachout_count": max_reachout_count,
                },
                headers=headers,
                timeout=30,
            )

            if response.status_code == 200:
                result = response.json()
                filtered_indices = result.get("selected_indices", [])

                # Get contacts at selected indices
                filtered_contacts = [
                    contacts[i] for i in filtered_indices if i < len(contacts)
                ]

                self.logger.info(
                    f"AI filtered to {len(filtered_contacts)} contacts. "
                    f"Thinking: {result.get('thinking', 'N/A')}"
                )

                return filtered_contacts[:MAX_RECRUITERS_PER_APPLICATION]
            else:
                self.logger.error(
                    f"AI filtering failed: {response.status_code} - {response.text}"
                )
                # Fallback: return first MAX_RECRUITERS_PER_APPLICATION contacts
                return contacts[:MAX_RECRUITERS_PER_APPLICATION]

        except Exception as e:
            self.logger.error(f"Error filtering contacts by AI: {e}")
            # Fallback: return first MAX_RECRUITERS_PER_APPLICATION contacts
            return contacts[:MAX_RECRUITERS_PER_APPLICATION]

    def _cleanup_browser(self):
        """Clean up browser resources"""
        if self.browser_operator:
            try:
                self.browser_operator.close()
            except Exception as e:
                self.logger.warning(f"Error closing browser: {e}")
            self.page = None

    def _extract_profile_data(self, contact: dict[str, Any]) -> dict[str, Any]:
        """
        Extract all profile data from LinkedIn profile page.  # noqa: E402

        Args:
            contact: Contact dictionary with basic info

        Returns:
            Dictionary with all extracted profile data
        """
        return {
            "subtitle": self._extract_contact_subtitle(),
            "image_url": self._extract_profile_image(),
            "about": self._extract_about_section(),
            "work_history": self._extract_work_history(),
            "education": self._extract_education(),
            "activities": self._extract_activities(),
            "connection_degree": self._extract_connection_degree(),
        }

    def _extract_contact_subtitle(self) -> str:
        """Extract contact subtitle (current role)"""
        try:
            return self.page.locator("div[class*=text-body-medium]").inner_text()
        except Exception as e:
            self.logger.debug(f"Failed to extract subtitle: {e}")
            return ""

    def _extract_profile_image(self) -> str:
        """Extract profile picture URL"""
        try:
            image_url = (
                self.page.locator(
                    "button[class*=pv-top-card-profile-picture__container]"
                )
                .locator("img")
                .first.get_attribute("src")
            )

            # Check if it's a placeholder/data URI (e.g., base64 1x1 transparent GIF)
            # LinkedIn uses these for lazy-loading, they're not actual profile pictures
            if image_url and image_url.startswith("data:"):
                self.logger.debug(f"Skipping placeholder data URI: {image_url[:50]}...")
                return ""

            return image_url or ""
        except Exception as e:
            self.logger.debug(f"Failed to extract profile image: {e}")
            return ""

    def _extract_about_section(self) -> str:
        """Extract about section text"""
        try:
            return (
                self.page.locator("div#about")
                .locator("..")
                .locator("div[data-generated-suggestion-target]")
                .inner_text()
            )
        except Exception as e:
            self.logger.debug(f"Failed to extract about section: {e}")
            return ""

    def _extract_work_history(self) -> str:
        """Extract work history section text"""
        try:
            return self.page.locator("div#experience").locator("..").inner_text()
        except Exception as e:
            self.logger.debug(f"Failed to extract work history: {e}")
            return ""

    def _extract_education(self) -> str:
        """Extract education section text"""
        try:
            return self.page.locator("div#education").locator("..").inner_text()
        except Exception as e:
            self.logger.debug(f"Failed to extract education: {e}")
            return ""

    def _extract_activities(self) -> str:
        """Extract activities section text"""
        try:
            return (
                self.page.locator("div#content_collections").locator("..").inner_text()
            )
        except Exception as e:
            self.logger.debug(f"Failed to extract activities: {e}")
            return ""

    def _extract_connection_degree(self) -> int:
        """Extract and parse connection degree"""
        try:
            connection_str = self.page.locator("span[class*=dist-value]").inner_text()

            if "1st" in connection_str:
                return 1
            elif "2nd" in connection_str:
                return 2
            else:
                return 3
        except Exception as e:
            self.logger.debug(f"Failed to extract connection degree: {e}")
            return 3

    def _enrich_contact_with_ai(
        self,
        name: str,
        current_role: str,
        profile_url: str,
        about_text: str,
        work_history_text: str,
        education_text: str,
        activities_text: str,
        job_title: str,
        company: str,
        job_description: str,
        user_resume_text: str,
    ) -> dict[str, Any]:
        """
        Enrich contact using AI through service-gateway.

        Args:
            name: Contact name
            current_role: Current role/title
            profile_url: LinkedIn profile URL
            about_text: Raw about section text
            work_history_text: Raw work history text
            education_text: Raw education text
            activities_text: Raw activities text
            job_title: Target job title
            company: Target company name
            job_description: Job description/requirements

        Returns:
            Dictionary with enriched contact data
        """
        try:
            self.logger.info(
                f"Enriching contact {name} with AI for " f"{job_title} at {company}"
            )

            # Get JWT token for authentication
            token = jwt_token_manager.get_token()
            headers = {"Content-Type": "application/json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            else:
                self.logger.warning("No JWT token available for contact enrichment")

            # Call service-gateway AI endpoint with raw text
            response = requests.post(
                f"{SERVICE_GATEWAY_URL}/api/contacts/enrich",
                json={
                    "name": name,
                    "current_role": current_role,
                    "profile_url": profile_url,
                    "about_text": about_text,
                    "work_history_text": work_history_text,
                    "education_text": education_text,
                    "activities_text": activities_text,
                    "job_title": job_title,
                    "company": company,
                    "job_description": job_description,
                    "user_resume_text": user_resume_text,
                },
                headers=headers,
                timeout=60,
            )

            if response.status_code == 200:
                result = response.json()
                self.logger.info(f"Successfully enriched contact {name} with AI")
                return {
                    "job_title": result.get("job_title", ""),
                    "about": result.get("about", ""),
                    "work_history": result.get("work_history", []),
                    "education": result.get("education", []),
                    "recent_activity": result.get("recent_activity", []),
                    "why_outreach": result.get("why_outreach", ""),
                    "personalized_outreach_tips": result.get(
                        "personalized_outreach_tips", []
                    ),
                    "draft_message": result.get("draft_message", ""),
                }
            else:
                self.logger.error(
                    "Contact enrichment API error "
                    f"{response.status_code}: {response.text}"
                )
                return {
                    "job_title": "",
                    "about": "",
                    "work_history": [],
                    "education": [],
                    "recent_activity": [],
                    "why_outreach": ("Unable to generate personalized outreach reason"),
                    "personalized_outreach_tips": [],
                    "draft_message": "",
                }

        except Exception as e:
            self.logger.error(f"Error enriching contact with AI: {e}")
            return {
                "job_title": "",
                "about": "",
                "work_history": [],
                "education": [],
                "recent_activity": [],
                "why_outreach": ("Unable to generate personalized outreach reason"),
                "personalized_outreach_tips": [],
                "draft_message": "",
            }

    def _upload_profile_pic_to_blob(
        self, image_url: str, contact_id: str
    ) -> str | None:
        """
        Download profile picture and upload to Azure Blob Storage.

        Args:
            image_url: LinkedIn profile picture URL
            contact_id: Unique contact ID for filename

        Returns:
            Blob URL of uploaded image or None if failed
        """
        try:
            if not image_url:
                return None

            # Download image from LinkedIn
            response = requests.get(
                image_url,
                timeout=10,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36"
                    )
                },
            )

            if response.status_code != 200:
                self.logger.warning(
                    f"Failed to download profile pic: " f"HTTP {response.status_code}"
                )
                return None

            # Get auth token
            token = jwt_token_manager.get_token()
            if not token:
                self.logger.error("No auth token available for blob upload")
                return None

            # Determine file extension from content type
            content_type = response.headers.get("Content-Type", "image/jpeg")
            if "jpeg" in content_type or "jpg" in content_type:
                ext = "jpg"
            elif "png" in content_type:
                ext = "png"
            elif "gif" in content_type:
                ext = "gif"
            elif "webp" in content_type:
                ext = "webp"
            else:
                ext = "jpg"  # default

            # Create filename
            filename = f"profile_pic_{contact_id}.{ext}"

            # Upload to blob storage via service gateway
            files = {"file": (filename, response.content, content_type)}

            upload_response = requests.post(
                (
                    f"{SERVICE_GATEWAY_URL}/api/blob/upload"
                    "?container=profile-pics&folder=contacts"
                ),
                headers={"Authorization": f"Bearer {token}"},
                files=files,
                timeout=30,
            )

            if upload_response.status_code == 200:
                result = upload_response.json()
                if result.get("success"):
                    blob_url = result.get("blob_url")
                    self.logger.info(f"Uploaded profile pic to: {blob_url}")
                    return blob_url
                else:
                    self.logger.error(f"Blob upload failed: {result}")
                    return None
            else:
                self.logger.error(
                    "Blob upload HTTP error "
                    f"{upload_response.status_code}: "
                    f"{upload_response.text}"
                )
                return None

        except requests.Timeout:
            self.logger.warning("Timeout downloading or uploading profile picture")
            return None
        except Exception as e:
            self.logger.warning(f"Error uploading profile pic to blob: {e}")
            return None

    def _save_contact_to_db(self, contact: dict[str, Any]) -> dict[str, Any] | None:
        """
        Save a single contact to database via supabase_client.

        Args:
            contact: Enriched contact dictionary

        Returns:
            Saved contact from database or None if failed  # noqa: E402
        """
        try:
            # Use supabase_client which handles JWT auth automatically
            saved_contact = supabase_client.create_contact(contact)
            return saved_contact

        except Exception as e:
            self.logger.error(f"Error saving contact to database: {e}")
            return None

    def _append_contact_to_application(
        self, application_id: str, contact_id: str
    ) -> None:
        """
        Append a contact ID to the application history's contact_ids array.

        Args:
            application_id: Application history record ID
            contact_id: Contact ID to append
        """
        try:
            # Get current application history
            app_history = supabase_client.get_application_history_by_id(application_id)
            if not app_history:
                self.logger.warning(f"Application {application_id} not found")
                return

            # Get existing contact_ids or initialize empty list
            contact_ids = app_history.get("contact_ids") or []

            # Append new contact if not already present
            if contact_id not in contact_ids:
                contact_ids.append(contact_id)

                # Update application history
                supabase_client.update_application_history(
                    application_id, {"contact_ids": contact_ids}
                )
                self.logger.info(
                    f"Appended contact {contact_id} to " f"application {application_id}"
                )

        except Exception as e:
            self.logger.error(f"Error appending contact to application: {e}")

    def _mark_collection_complete(self, application_id: str) -> None:
        """
        Mark contact collection as complete for an application.

        Args:
            application_id: Application history record ID
        """
        try:
            supabase_client.update_application_history(
                application_id, {"contact_collection_complete": True}
            )
            self.logger.info(
                "Marked contact collection complete for "
                f"application {application_id}"
            )
        except Exception as e:
            self.logger.error(f"Error marking collection complete: {e}")
