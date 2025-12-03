"""
ConfigReader v2 - Database-driven configuration
Reads user configuration from Supabase database instead of local files
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests  # noqa: E402

from constants import RESUME_DIR  # noqa: E402
from services.supabase_client import supabase_client  # noqa: E402
from shared.config_reader.config_data_map import ConfigMapper  # noqa: E402
from shared.models import Resume  # noqa: E402

logger = logging.getLogger(__name__)


@dataclass
class ModelConfig:
    """Model configuration for AI operations"""

    name: str = "gpt-4.1"
    additional_system_prompt: str = ""
    generate_ats_optimized_resume: bool = False
    on_device_models: List[str] = None

    def __post_init__(self):
        if self.on_device_models is None:
            self.on_device_models = []


@dataclass
class SettingsConfig:
    """Application settings configuration"""

    skip_optional_questions: bool = True
    show_browser: bool = True
    auto_apply: bool = True
    submit_confident_application: bool = False
    record_unseen_faqs_and_skip_application: bool = True
    send_connection_to_hiring_team: bool = True
    generate_ats_optimized_resume: bool = False
    generate_cover_letter: bool = True
    daily_application_limit: int = 10
    search_mode: bool = False  # Search-only mode: browse jobs without applying


@dataclass
class FiltersConfig:
    """Job search filter configuration"""

    job_description: str = ""  # Job title/keywords for search (Indeed, LinkedIn)
    location: str = ""  # Simple location string (e.g., "San Francisco, CA")
    country: str = "usa"
    salary_bound: Optional[int] = None
    experience_levels: List[int] = None
    remote_types: List[int] = None
    job_types: List[str] = None
    specific_locations: List[str] = None
    blacklist_companies: List[str] = None
    semantic_instructions: str = ""
    skip_previously_skipped_jobs: bool = True
    skip_staffing_companies: bool = False
    staffing_companies: set[
        str
    ] = None  # Set of known staffing company names (lowercase)

    def __post_init__(self):
        if self.experience_levels is None:
            self.experience_levels = []
        if self.remote_types is None:
            self.remote_types = []
        if self.job_types is None:
            self.job_types = []
        if self.specific_locations is None:
            self.specific_locations = []
        if self.blacklist_companies is None:
            self.blacklist_companies = []
        if self.staffing_companies is None:
            self.staffing_companies = set()


@dataclass
class PersonalizedApplicationsConfig:
    """Personalized application configuration"""

    cover_letter_instructions: str = ""
    message_to_hiring_team: str = ""
    cover_letter_section: Dict[str, Any] = None

    def __post_init__(self):
        if self.cover_letter_section is None:
            self.cover_letter_section = {}


@dataclass
class ProfileConfig:
    """User profile configuration loaded from Supabase tables  # noqa: E402

    Note: Authentication is handled by Supabase auth.users table.
    User data comes from: user_faq table, resumes table, workflow_runs table.
    """

    email: str = ""
    additional_profile_info: str = ""
    resume: str = (
        ""  # Resume text content (changed from Dict to str to fix ATS analysis)
    )
    resume_summary: Dict[str, Any] = None
    faq_template: Dict[str, Any] = None
    phone_country_code: str = "+1"
    resume_path: str = ""
    resume_url: str = ""
    resume_id: Optional[str] = None  # Resume ID from database  # noqa: E402
    ats_resume_template: str = ""
    selected_ats_template_id: Optional[str] = None
    additional_experience: str = ""
    # Cover letter template fields
    selected_cover_letter_template_id: Optional[str] = None
    cover_letter_html_content: str = ""
    cover_letter_user_instruction: str = ""

    def __post_init__(self):
        # resume is now a string, no need to initialize
        if self.resume_summary is None:
            self.resume_summary = {}
        if self.faq_template is None:
            self.faq_template = {}

    def empty_resume_path(self) -> bool:
        """Check if resume path is empty (compatibility with v1)"""
        return not bool(self.resume_path.strip() if self.resume_path else True)


class ConfigReader:
    """
    v2 ConfigReader that reads configuration from Supabase database  # noqa: E402
    Replaces v1's file-based configuration system

    Data Sources:
    ┌─────────────────┬──────────────────┬────────────────────────────────┐
    │ Data Type       │ Source Table     │ Model                          │
    ├─────────────────┼──────────────────┼────────────────────────────────┤
    │ Resume data     │ resumes          │ Resume model                   │
    │ FAQ templates   │ user_faq         │ UserFaq model                  │
    │ Filter settings │ workflow_runs    │ WorkflowRun model              │
    │ App settings    │ workflow_runs    │ WorkflowRun model              │
    │ Authentication  │ auth.users       │ Supabase built-in              │
    └─────────────────┴──────────────────┴────────────────────────────────┘

    Usage:
    1. config_reader.load_configuration() - loads FAQ & resume data
    2. config_reader.get_current_workflow_run_config(run_id)
       - loads filters & app settings
    """

    def __init__(self, user_id: str, workflow_run_id: str):
        """
        Initialize ConfigReader v2

        Args:
            user_id: User ID (if None, will use authenticated user from service)
            workflow_run_id: Workflow run ID to load configuration from
        """
        self.user_id = user_id
        self.workflow_run_id = workflow_run_id
        self.model = ModelConfig()
        self.settings = SettingsConfig()
        self.filters = FiltersConfig()
        self.personalized_applications = PersonalizedApplicationsConfig()
        self.profile = ProfileConfig()
        self._loaded = False

        # Resume validation attributes (compatibility with v1)
        self.using_valid_ats_resume_template = False
        self.using_valid_resume = False

    def load_configuration(self) -> bool:
        """
        Load user configuration from database  # noqa: E402

        Sources:
        - Resume data: from Resume model (resumes table)  # noqa: E402
        - FAQ data: from UserFaq model (user_faq table)  # noqa: E402
        - Filter settings: from WorkflowRun model (workflow_runs table) -
          loaded separately via get_current_workflow_run_config

        Note: Uses Supabase auth.users for authentication,
        no separate user_profiles table needed

        Returns:
            True if configuration loaded successfully, False otherwise
        """
        try:
            logger.info("Loading user configuration (Supabase auth-based)")

            # Initialize with defaults first
            self.model = ModelConfig()
            self.settings = SettingsConfig()
            self.filters = FiltersConfig()
            self.personalized_applications = PersonalizedApplicationsConfig()
            self.profile = ProfileConfig()

            # Load user-specific data from database tables
            self._load_config()

            # Load workflow run settings (including ATS template selection)
            self._load_workflow_run_settings()

            self._loaded = True
            logger.info("Configuration loaded successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            return False

    def _load_faq_config(self):
        """Load FAQ configuration from database"""  # noqa: E402
        try:
            logger.info(f"Loading FAQ for user_id: {self.user_id}")
            user_faq_models = supabase_client.get_user_faq(self.user_id)
            if (
                user_faq_models
                and isinstance(user_faq_models, list)
                and len(user_faq_models) > 0
            ):
                # Convert list of FAQ dictionaries to a single merged dictionary
                faq_dict = {}
                for faq_model in user_faq_models:
                    faq_format = faq_model.to_faq_template_format()
                    faq_dict.update(faq_format)
                self.profile.faq_template = faq_dict
                logger.info(
                    f"FAQ: Loaded {len(faq_dict)} entries from user_faq table"
                )  # noqa: E402
            else:
                logger.warning(
                    f"FAQ: No entries found in user_faq table for user {self.user_id}"
                )
        except Exception as e:
            logger.error(f"Error loading FAQ config: {e}")

    def _load_additional_info(self):
        """Load additional info (about me) from database"""
        try:
            logger.info(f"Loading additional info for user_id: {self.user_id}")
            additional_info_body = supabase_client.get_user_additional_info()
            if additional_info_body:
                self.profile.additional_profile_info = additional_info_body
                logger.info(
                    f"Additional Info: Loaded {len(self.profile.additional_profile_info)} characters from user_additional_info table"
                )
            else:
                logger.info(
                    f"Additional Info: No entries found in user_additional_info table for user {self.user_id}"
                )
                self.profile.additional_profile_info = ""
        except Exception as e:
            logger.error(f"Error loading additional info: {e}")
            self.profile.additional_profile_info = ""

    def _load_resume_config(self, resume_id: str):
        """Load resume configuration from database"""  # noqa: E402
        try:
            logger.info(f"Loading resume for user_id: {self.user_id}")
            resume_model = supabase_client.get_resume_by_id(resume_id)
            if resume_model:
                resume_dict = resume_model.to_dict()
                self.profile.resume = resume_dict.get("resume_content", "")
                # Store the resume ID for later use
                self.profile.resume_id = resume_id
                # For v2, we'll use the file path if available, otherwise create a placeholder  # noqa: E501
                self.profile.resume_url = resume_dict.get("blob_url")

                # Download and save resume to local directory
                local_resume_path = self._download_and_save_resume(resume_model)
                if local_resume_path:
                    self.profile.resume_path = local_resume_path
                    logger.info(
                        f"Resume: Downloaded and saved locally - {resume_dict.get('file_name', 'Unknown')}"  # noqa: E501
                    )
                else:
                    logger.warning("Failed to download resume locally, using blob URL")
                    self.profile.resume_path = ""

                logger.info(
                    f"Resume: Loaded from workflow run - {resume_dict.get('file_name', 'Unknown')}"  # noqa: E501
                )
            else:
                logger.warning(
                    f"Resume: No resume text found for resume_id: {resume_id}"
                )
                # Clear resume data for validation
                self.profile.resume_id = None
                self.profile.resume_path = ""
        except Exception as e:
            logger.error(f"Error loading resume config: {e}")
            self.profile.resume_id = None
            self.profile.resume_path = ""

    def _load_config(self):
        """
        Load profile configuration from database tables  # noqa: E402

        Sources:
        - FAQ data: UserFaq model from user_faq table  # noqa: E402
        - Resume data: Resume model from resumes table  # noqa: E402

        Note: Filter settings (salary_bound, country, etc.) are loaded separately
        from WorkflowRun model via get_current_workflow_run_config()  # noqa: E402
        """
        try:
            # Initialize with empty defaults first
            self.profile.faq_template = {}
            self.profile.resume = ""
            self.profile.resume_summary = {}
            self.profile.additional_profile_info = ""

            # Load real user data from Supabase tables (auth.users provides authentication)  # noqa: E501
            if supabase_client and hasattr(supabase_client, "_make_request"):
                try:
                    # 1. Load FAQ templates from UserFaq model (user_faq table)
                    self._load_faq_config()

                    # 2. Load additional info (about me) from user_additional_info table
                    self._load_additional_info()

                    # 3. load workflow run data
                    logger.info(
                        f"Loading workflow run data for workflow_run_id: {self.workflow_run_id}"  # noqa: E501
                    )
                    self.workflow_run_config = self.get_workflow_run_config_by_run_id()

                    # 4. Map workflow run data to config objects
                    if self.workflow_run_config:
                        # Map settings
                        self.settings.auto_apply = self.workflow_run_config.get(
                            "auto_apply", False
                        )
                        self.settings.submit_confident_application = (
                            self.workflow_run_config.get(
                                "submit_confident_application", False
                            )
                        )
                        self.settings.generate_cover_letter = (
                            self.workflow_run_config.get("generate_cover_letter", True)
                        )
                        self.settings.send_connection_to_hiring_team = (
                            self.workflow_run_config.get(
                                "send_connection_request", False
                            )
                        )
                        self.settings.daily_application_limit = (
                            self.workflow_run_config.get("daily_application_limit", 10)
                        )
                        self.settings.generate_ats_optimized_resume = (
                            self.workflow_run_config.get("use_ats_optimized", False)
                        )
                        # Load search_mode from agent_run_template.is_search_agent
                        self._load_search_mode_from_template()
                        # Map filter settings with platform_filters support
                        # Priority: platform_filters first, fallback to legacy fields
                        platform_filters = self.workflow_run_config.get(
                            "platform_filters"
                        )
                        platform = self.workflow_run_config.get("platform", "linkedin")

                        if (
                            platform_filters
                            and isinstance(platform_filters, dict)
                            and platform in platform_filters
                        ):
                            # NEW FORMAT: Read from platform_filters JSONB
                            logger.info(f"Using platform_filters for {platform}")
                            filters = platform_filters[platform]
                            self.filters.country = filters.get("country")
                            self.filters.salary_bound = filters.get("salary_bound")
                            self.filters.experience_levels = filters.get(
                                "experience_levels", []
                            )
                            self.filters.remote_types = filters.get("remote_types", [])
                            self.filters.specific_locations = filters.get(
                                "specific_locations", []
                            )
                        else:
                            # OLD FORMAT: Fallback to legacy columns for backward compatibility
                            logger.info(
                                f"No platform_filters found for {platform} - falling back to legacy fields"
                            )
                            self.filters.country = self.workflow_run_config.get(
                                "country"
                            )
                            self.filters.salary_bound = self.workflow_run_config.get(
                                "salary_bound"
                            )
                            self.filters.experience_levels = (
                                self.workflow_run_config.get("experience_levels", [])
                            )
                            self.filters.remote_types = self.workflow_run_config.get(
                                "remote_types", []
                            )
                            self.filters.specific_locations = (
                                self.workflow_run_config.get("specific_locations", [])
                            )

                        # Common filter settings (not platform-specific)
                        # Read search_keywords directly
                        search_keywords = self.workflow_run_config.get(
                            "search_keywords", []
                        )
                        # For backwards compatibility, store first keyword in job_description field
                        self.filters.job_description = (
                            search_keywords[0]
                            if search_keywords and len(search_keywords) > 0
                            else ""
                        )
                        # Read location from location_preferences (plain text)
                        self.filters.location = self.workflow_run_config.get(
                            "location_preferences", ""
                        )
                        self.filters.job_types = self.workflow_run_config.get(
                            "job_types", []
                        )
                        self.filters.blacklist_companies = self.workflow_run_config.get(
                            "blacklist_companies", []
                        )
                        self.filters.semantic_instructions = (
                            self.workflow_run_config.get("semantic_instructions", "")
                        )
                        self.filters.skip_previously_skipped_jobs = (
                            self.workflow_run_config.get(
                                "skip_previously_skipped_jobs", True
                            )
                        )
                        self.filters.skip_staffing_companies = (
                            self.workflow_run_config.get(
                                "skip_staffing_companies", False
                            )
                        )

                        # Load staffing companies list if enabled
                        if self.filters.skip_staffing_companies:
                            self._load_staffing_companies()

                        # Map personalized applications
                        self.personalized_applications.cover_letter_instructions = (
                            self.workflow_run_config.get(
                                "cover_letter_instructions", ""
                            )
                        )
                        self.personalized_applications.message_to_hiring_team = (
                            self.workflow_run_config.get("message_to_hiring_team", "")
                        )

                    # 5. load resume data (only if not using ATS optimized)
                    use_ats_optimized = (
                        self.workflow_run_config.get("use_ats_optimized", False)
                        if self.workflow_run_config
                        else False
                    )
                    if use_ats_optimized:
                        logger.info(
                            "Using ATS optimized mode - skipping resume loading"
                        )
                        self.profile.resume = ""
                        self.profile.resume_path = ""
                        self.profile.resume_url = ""
                        self.profile.resume_id = None
                    else:
                        logger.info("Using regular resume mode - loading resume")
                        # Use selected_resume_id instead of resume_id
                        selected_resume_id = (
                            self.workflow_run_config.get("selected_resume_id", "")
                            if self.workflow_run_config
                            else ""
                        )
                        # Fallback to resume_id for backward compatibility
                        if not selected_resume_id:
                            selected_resume_id = (
                                self.workflow_run_config.get("resume_id", "")
                                if self.workflow_run_config
                                else ""
                            )
                        self._load_resume_config(selected_resume_id)

                except Exception as db_error:
                    logger.error(f"Database access failed (using defaults): {db_error}")
                    import traceback  # noqa: E402

                    logger.debug(f"Full error traceback: {traceback.format_exc()}")
            else:
                logger.info("Database client not configured, using defaults")

            logger.debug(
                f"Profile config summary: FAQ={len(self.profile.faq_template)} entries, Resume={'Yes' if self.profile.resume else 'No'}"  # noqa: E501
            )

        except Exception as e:
            logger.error(f"Error in _load_profile_config: {e}")
            # Ensure we always have defaults even on error
            self.profile.faq_template = {}
            self.profile.resume = ""
            self.profile.resume_summary = {}
            self.profile.additional_profile_info = ""

    def is_loaded(self) -> bool:
        """Check if configuration has been loaded"""
        return self._loaded

    def update_filter(self, filter_name: str, value: Any) -> bool:
        """
        Update a filter configuration value

        Args:
            filter_name: Name of the filter to update
            value: New value for the filter

        Returns:
            True if updated successfully, False otherwise
        """
        try:
            if hasattr(self.filters, filter_name):
                setattr(self.filters, filter_name, value)
                logger.info(
                    "Updated filter %s to %s (in-memory only)",
                    filter_name,
                    value,
                )
                return True
            else:
                logger.error(f"Unknown filter: {filter_name}")
                return False

        except Exception as e:
            logger.error(f"Error updating filter {filter_name}: {e}")
            return False

    def get_workflow_run_config_by_run_id(self) -> Optional[Dict[str, Any]]:
        """
        Load configuration from the most recent workflow run of a
        specific workflow run

        Returns:
            Configuration dict or None if not found
        """
        try:
            logger.info(
                "Loading configuration from most recent run of workflow %s",
                self.workflow_run_id,
            )

            if supabase_client and hasattr(supabase_client, "_make_request"):
                # Get the most recent workflow run for this workflow
                logger.info(
                    "Calling supabase_client.get_workflow_run_by_run_id with ID: %s",
                    self.workflow_run_id,
                )
                workflow_run_model = supabase_client.get_workflow_run_by_run_id(
                    self.workflow_run_id
                )

                if workflow_run_model:
                    result_dict = workflow_run_model.to_dict()
                    logger.info(f"Converted to dict: {result_dict}")
                    return result_dict
                else:
                    logger.warning("workflow_run_model is None")
                    return None
            else:
                logger.warning("Database client not configured")
                return None

        except Exception as e:
            logger.error(f"Error loading workflow run config by run_id: {e}")
            return None

    def get_platform_filters(self) -> Optional[Dict[str, Any]]:
        """
        Get platform_filters from the workflow run configuration

        Returns:
            Platform filters dict or None if not found
        """
        try:
            if self.workflow_run_config:
                return self.workflow_run_config.get("platform_filters")
            return None
        except Exception as e:
            logger.error(f"Error getting platform filters: {e}")
            return None

    def get_job_search_criteria_string(self) -> str:
        """
        Build job search criteria string from filters for InterestMarker.
        Reads from platform_filters only.

        Returns:
            Formatted job search criteria string
        """
        criteria_parts = []

        # Add semantic instructions first (most important custom criteria)
        if self.filters.semantic_instructions:
            criteria_parts.append(
                f"Custom criteria: {self.filters.semantic_instructions}"
            )

        # Add search keywords (job description)
        if self.filters.job_description:
            criteria_parts.append(self.filters.job_description)

        # Add location preferences from platform_filters
        if self.filters.country:
            criteria_parts.append(f"country: {self.filters.country}")

        if self.filters.specific_locations:
            if (
                isinstance(self.filters.specific_locations, list)
                and self.filters.specific_locations
            ):
                criteria_parts.append(
                    f"locations: {', '.join(self.filters.specific_locations)}"
                )
            elif (
                isinstance(self.filters.specific_locations, str)
                and self.filters.specific_locations
            ):
                criteria_parts.append(f"locations: {self.filters.specific_locations}")

        # Add salary preference from platform_filters
        if self.filters.salary_bound:
            criteria_parts.append(f"minimum salary: {self.filters.salary_bound}")

        # Add experience levels from platform_filters
        if self.filters.experience_levels:
            if (
                isinstance(self.filters.experience_levels, list)
                and self.filters.experience_levels
            ):
                criteria_parts.append(
                    f"experience level: {', '.join(map(str, self.filters.experience_levels))}"
                )
            elif self.filters.experience_levels:
                criteria_parts.append(
                    f"experience level: {self.filters.experience_levels}"
                )

        # Add remote work preferences from platform_filters
        if self.filters.remote_types:
            if (
                isinstance(self.filters.remote_types, list)
                and self.filters.remote_types
            ):
                criteria_parts.append(
                    f"work type: {', '.join(map(str, self.filters.remote_types))}"
                )
            elif self.filters.remote_types:
                criteria_parts.append(f"work type: {self.filters.remote_types}")

        # Add job types (common field, not in platform_filters)
        if self.filters.job_types:
            if isinstance(self.filters.job_types, list) and self.filters.job_types:
                criteria_parts.append(f"job type: {', '.join(self.filters.job_types)}")
            elif self.filters.job_types:
                criteria_parts.append(f"job type: {self.filters.job_types}")

        # Combine all criteria
        return ", ".join(criteria_parts) if criteria_parts else "software engineer"

    def to_dict(self) -> Dict[str, Any]:
        """
        Export configuration as dictionary (useful for debugging or API responses)

        Returns:
            Configuration as dict with readable values for experience_levels, remote_types, and job_types  # noqa: E501
        """
        # Get raw filters dict
        filters_raw = {
            "country": self.filters.country,
            "salary_bound": self.filters.salary_bound,
            "experience_levels": self.filters.experience_levels,
            "remote_types": self.filters.remote_types,
            "job_types": self.filters.job_types,
            "specific_locations": self.filters.specific_locations,
            "blacklist_companies": self.filters.blacklist_companies,
            "semantic_instructions": self.filters.semantic_instructions,
            "skip_previously_skipped_jobs": self.filters.skip_previously_skipped_jobs,
            "skip_staffing_companies": self.filters.skip_staffing_companies,
        }

        # Convert the three specified fields to readable values
        filters_readable = ConfigMapper.convert_all(filters_raw)

        return {
            "model": {
                "name": self.model.name,
            },
            "settings": {
                "submit_confident_application": self.settings.submit_confident_application,  # noqa: E501
                "send_connection_to_hiring_team": self.settings.send_connection_to_hiring_team,  # noqa: E501
                "generate_ats_optimized_resume": self.settings.generate_ats_optimized_resume,  # noqa: E501
                "generate_cover_letter": self.settings.generate_cover_letter,
            },
            "filters": filters_readable,
            "personalized_application": {
                "cover_letter_instructions": self.personalized_applications.cover_letter_instructions,  # noqa: E501
                "message_to_hiring_team": self.personalized_applications.message_to_hiring_team,  # noqa: E501
            },
            "profile": {
                "email": self.profile.email,
                "additional_profile_info": self.profile.additional_profile_info,
                "faq_template": self.profile.faq_template,
                "resume": self.profile.resume,
                "selected_ats_template_id": self.profile.selected_ats_template_id,
                "selected_cover_letter_template_id": self.profile.selected_cover_letter_template_id,  # noqa: E501
                "cover_letter_html_content": self.profile.cover_letter_html_content,
                "cover_letter_user_instruction": self.profile.cover_letter_user_instruction,  # noqa: E501
            },
        }

    def is_valid_resume(self) -> bool:
        """
        Check if resume configuration is valid (compatibility with v1)

        Returns:
            True if resume is valid, False otherwise
        """
        # Check for ATS template usage
        self.using_valid_ats_resume_template = (
            self.settings.generate_ats_optimized_resume
            and self.profile.ats_resume_template
        )

        # Check for regular resume usage
        self.using_valid_resume = (
            not self.settings.generate_ats_optimized_resume
            and os.path.exists(self.profile.resume_path)
        )

        return self.using_valid_ats_resume_template or self.using_valid_resume

    def _download_and_save_resume(self, resume_model: Resume) -> Optional[str]:
        """
        Download resume from blob storage and save to local RESUME_DIR  # noqa: E402

        Args:
            resume_model: Resume model with blob_url

        Returns:
            Local file path if successful, None if failed
        """
        try:
            if not resume_model.blob_url:
                logger.warning("No blob_url available for resume download")
                return None

            # Create filename from resume model
            file_extension = Path(resume_model.file_name).suffix or ".pdf"
            local_filename = f"{resume_model.id}{file_extension}"
            local_file_path = os.path.join(RESUME_DIR, local_filename)

            # Check if file already exists locally
            if os.path.exists(local_file_path):
                logger.info(f"Resume already exists locally: {local_file_path}")
                return local_file_path

            # Method 1: Try direct download from blob_url (public URLs)
            try:
                logger.info(f"Attempting direct download from: {resume_model.blob_url}")
                file_response = requests.get(resume_model.blob_url, timeout=30)
                file_response.raise_for_status()

                # Save to local directory
                with open(local_file_path, "wb") as f:
                    f.write(file_response.content)

                logger.info(f"Resume downloaded directly and saved: {local_file_path}")
                return local_file_path

            except Exception as direct_error:
                logger.warning(f"Direct download failed: {direct_error}")
                logger.info("Falling back to service gateway download...")

        except Exception as e:
            logger.error(f"Error downloading and saving resume: {e}")
            return None

    @property
    def application(self):
        """Compatibility property to access settings as 'application'"""
        return self.settings

    def _load_workflow_run_settings(self):
        """
        Load workflow run settings including ATS template selection into profile
        """
        try:
            # Use already loaded workflow run config from _load_config()
            if self.workflow_run_config:
                # Load ATS template ID into profile
                ats_template_id = self.workflow_run_config.get(
                    "selected_ats_template_id"
                )
                self.profile.selected_ats_template_id = ats_template_id
                logger.info(
                    f"Loaded ATS template ID: {self.profile.selected_ats_template_id}"
                )

                # Load ATS template HTML if template ID is available
                if ats_template_id:
                    self._load_ats_template_html(ats_template_id)

                # Load cover letter template ID into profile
                cover_letter_template_id = self.workflow_run_config.get(
                    "selected_cover_letter_template_id"
                )
                self.profile.selected_cover_letter_template_id = (
                    cover_letter_template_id
                )
                logger.info(
                    "Loaded cover letter template ID: "
                    f"{self.profile.selected_cover_letter_template_id}"
                )

                # Load cover letter template HTML and user instruction
                # if template ID is available
                if cover_letter_template_id:
                    self._load_cover_letter_template_data(cover_letter_template_id)
            else:
                logger.warning(
                    "No workflow run data found - this might be due to "
                    "authentication issues"
                )
        except Exception as e:
            logger.error(f"Error loading workflow run settings: {e}")
            import traceback  # noqa: E402

            logger.error(f"Traceback: {traceback.format_exc()}")

    def _load_ats_template_html(self, template_id: str):
        """
        Load ATS template HTML from service gateway and set ats_resume_template
        """
        try:
            from services.jwt_token_manager import jwt_token_manager  # noqa: E402

            # Get JWT token for authentication
            token = jwt_token_manager.get_token()
            if not token:
                logger.warning("No JWT token available - cannot load ATS template HTML")
                return

            # Call service gateway to get ATS template
            from constants import SERVICE_GATEWAY_URL  # noqa: E402

            headers = {"Authorization": f"Bearer {token}"}
            template_url = f"{SERVICE_GATEWAY_URL}/api/ats/template?id={template_id}"
            response = requests.get(template_url, headers=headers)

            if response.status_code == 200:
                template_data = response.json()
                if template_data.get("success") and template_data.get("template"):
                    template = template_data["template"]
                    original_html = template.get("original_html")
                    additional_experience = template.get("additional_experience", "")
                    original_resume_text = template.get("original_resume_text", "")

                    if original_html:
                        # Set the ats_resume_template to the original HTML
                        self.profile.ats_resume_template = original_html
                        # Also store additional experience for later use
                        self.profile.additional_experience = additional_experience
                        # Store original resume text for ATS scoring
                        self.profile.resume = original_resume_text
                        logger.info(
                            "Loaded ATS template HTML (length: %s), "
                            "resume text (length: %s)",
                            len(original_html),
                            len(original_resume_text),
                        )
                    else:
                        logger.warning("ATS template found but no original_html")
                else:
                    logger.warning(f"Failed to get ATS template: {template_data}")
            elif response.status_code == 404:
                logger.warning(
                    "ATS template not found: %s. User needs to create "
                    "an ATS template first.",
                    template_id,
                )
                # Clear the template ID since it's invalid
                self.profile.selected_ats_template_id = None
            else:
                logger.warning(
                    "Failed to load ATS template: %s - %s",
                    response.status_code,
                    response.text,
                )

        except Exception as e:
            logger.error(f"Error loading ATS template HTML: {e}")
            import traceback  # noqa: E402

            logger.error(f"Traceback: {traceback.format_exc()}")

    def _load_cover_letter_template_data(self, template_id: str):
        """
        Load cover letter template HTML content and user instruction from database
        """
        try:
            # Load cover letter template from database using supabase_client
            if supabase_client and hasattr(supabase_client, "_make_request"):
                logger.info(f"Loading cover letter template: {template_id}")

                # Get cover letter template from database
                cover_letter_template = supabase_client.get_cover_letter_template_by_id(
                    template_id
                )

                if cover_letter_template:
                    # Store HTML content and user instruction in profile
                    self.profile.cover_letter_html_content = (
                        cover_letter_template.html_content or ""
                    )
                    self.profile.cover_letter_user_instruction = (
                        cover_letter_template.user_instruction or ""
                    )

                    logger.info(
                        f"Loaded cover letter template: {cover_letter_template.name} "
                        f"(HTML length: {len(self.profile.cover_letter_html_content)}, "
                        f"Instruction length: {len(self.profile.cover_letter_user_instruction)})"  # noqa: E501
                    )
                else:
                    logger.warning(f"Cover letter template not found: {template_id}")
                    # Clear the template ID since it's invalid
                    self.profile.selected_cover_letter_template_id = None
                    self.profile.cover_letter_html_content = ""
                    self.profile.cover_letter_user_instruction = ""
            else:
                logger.warning(
                    "Database client not configured - cannot load cover letter template"  # noqa: E501
                )

        except Exception as e:
            logger.error(f"Error loading cover letter template data: {e}")
            import traceback  # noqa: E402

            logger.error(f"Traceback: {traceback.format_exc()}")
            # Clear template data on error
            self.profile.cover_letter_html_content = ""
            self.profile.cover_letter_user_instruction = ""

    def _load_staffing_companies(self):
        """
        Load set of known staffing companies from the database  # noqa: E402
        """
        try:
            if supabase_client and hasattr(supabase_client, "_make_request"):
                logger.info("Loading staffing companies from database")  # noqa: E402

                # Get staffing companies using supabase_client
                companies = supabase_client.get_staffing_companies()

                if companies:
                    # Extract company names and convert to lowercase as a set
                    self.filters.staffing_companies = {
                        company.get("company_name", "").lower()
                        for company in companies
                        if company.get("company_name")
                    }
                    logger.info(
                        f"Loaded {len(self.filters.staffing_companies)} staffing companies"  # noqa: E501
                    )
                else:
                    logger.info("No staffing companies found in database")
                    self.filters.staffing_companies = set()
            else:
                logger.warning(
                    "Database client not configured - cannot load staffing companies"
                )
                self.filters.staffing_companies = set()

        except Exception as e:
            logger.error(f"Error loading staffing companies: {e}")
            import traceback  # noqa: E402

            logger.error(f"Traceback: {traceback.format_exc()}")
            self.filters.staffing_companies = []

    def _load_search_mode_from_template(self):
        """
        Load search_mode from agent_run_template.is_search_agent

        The workflow_run has agent_run_template_id, and the template has
        is_search_agent boolean. This determines if the bot should browse
        jobs without applying (search mode).
        """
        try:
            # Default to False
            self.settings.search_mode = False

            if not self.workflow_run_config:
                return

            agent_run_template_id = self.workflow_run_config.get(
                "agent_run_template_id"
            )
            if not agent_run_template_id:
                logger.info("No agent_run_template_id in workflow run config")
                return

            # Fetch the agent_run_template from database
            agent_run_template = supabase_client.get_agent_run_template_by_id(
                agent_run_template_id
            )

            if agent_run_template:
                self.settings.search_mode = agent_run_template.is_search_agent
                logger.info(
                    f"Loaded search_mode={self.settings.search_mode} from "
                    f"agent_run_template '{agent_run_template.name}'"
                )
            else:
                logger.warning(
                    f"Agent run template {agent_run_template_id} not found, "
                    "defaulting search_mode to False"
                )

        except Exception as e:
            logger.error(f"Error loading search_mode from template: {e}")
            import traceback  # noqa: E402

            logger.error(f"Traceback: {traceback.format_exc()}")
            self.settings.search_mode = False

    @property
    def ATS_RESUME_TEMPLATE_DIR(self):
        """ATS resume template directory (placeholder for v2)"""
        return "ats_resume_templates"


# Global instance for easy access
# config_reader = ConfigReader()


if __name__ == "__main__":

    def main():
        config_reader = ConfigReader(
            user_id="1d04c54f-f94c-4a7e-b381-1c18ef882bcc",
            workflow_run_id="75cbbd8b-dc6a-40ef-bdc1-a6d768b672a7",
        )
        config_reader.load_configuration()
        logger.info(config_reader.to_dict())

    main()
