"""
WorkflowRun model for Supabase workflow_runs table
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field

CountryEnum = Literal[
    "usa",
    "canada",
    "uk",
    "germany",
    "france",
    "netherlands",
    "sweden",
    "norway",
    "finland",
]
StatusEnum = Literal["pending", "running", "paused", "completed", "failed", "cancelled"]
RemotePreferenceEnum = Literal["remote", "hybrid", "onsite"]
CompanySizeEnum = Literal["startup", "small", "medium", "large", "enterprise"]
PlatformEnum = Literal[
    "linkedin",
    "indeed",
    "ziprecruiter",
    "glassdoor",
    "dice",
    "autonomous",
]


class WorkflowRun(BaseModel):
    """Model for public.workflow_runs table"""

    id: UUID
    user_id: UUID
    workflow_id: str
    run_name: Optional[str] = None
    status: StatusEnum = "pending"
    platform: PlatformEnum = "linkedin"
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Job search criteria
    blacklist_companies: Optional[Union[List[str], Dict[str, Any]]] = None
    location_preferences: Optional[str] = None
    salary_range: Optional[Union[int, str, Dict[str, Any]]] = None
    job_types: Optional[Union[List[str], Dict[str, Any]]] = None
    experience_level: Optional[str] = None

    # Application settings
    generate_cover_letter: Optional[bool] = True
    send_connection_request: Optional[bool] = False
    auto_apply: Optional[bool] = False
    submit_confident_application: Optional[bool] = False
    daily_application_limit: Optional[int] = 10
    selected_resume_id: Optional[UUID] = None
    selected_ats_template_id: Optional[str] = None
    selected_cover_letter_template_id: Optional[str] = None
    use_ats_optimized: Optional[bool] = False
    skip_previously_skipped_jobs: Optional[bool] = True
    skip_staffing_companies: Optional[bool] = True

    # Advanced search
    search_keywords: Optional[Union[List[str], Dict[str, Any]]] = None
    exclude_keywords: Optional[Union[List[str], Dict[str, Any]]] = None
    company_size_preference: Optional[str] = None
    industry_preferences: Optional[Union[List[str], Dict[str, Any]]] = None
    remote_preference: Optional[str] = None

    # Statistics
    jobs_found: Optional[int] = 0
    applications_sent: Optional[int] = 0
    responses_received: Optional[int] = 0
    interviews_scheduled: Optional[int] = 0

    # System fields
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    infinite_hunt_session_id: Optional[str] = Field(
        None,
        description="ID of the infinite hunt session that created this workflow run",
    )
    config_reasoning_by_infinite_hunt: Optional[str] = Field(
        None,
        description="AI reasoning for why this config was generated in infinite hunt mode",
    )
    agent_run_template_id: Optional[str] = Field(
        None,
        description="ID of the agent run template used for this workflow run",
    )

    # NEW: Platform-specific filters (JSONB)
    platform_filters: Optional[Dict[str, Any]] = Field(
        None,
        description="Platform-specific filters in JSONB format. NULL = use old columns. "
        "Format: {'linkedin': {...}, 'indeed': {...}}",
    )

    # OLD: Location and criteria fields (kept for backward compatibility)
    # These will be deprecated after migration period
    country: Optional[CountryEnum] = "usa"
    salary_bound: Optional[int] = Field(None, ge=0)
    experience_levels: Optional[List[int]] = Field(
        None, description="Array of 1-6 representing experience levels"
    )
    remote_types: Optional[List[int]] = Field(
        None, description="Array of 1-3 representing remote preferences"
    )
    specific_locations: Optional[List[str]] = None
    semantic_instructions: Optional[str] = None
    headless_on: Optional[bool] = False

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda dt: dt.isoformat() if dt else None,
            UUID: lambda uuid: str(uuid) if uuid else None,
        }

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for config reader"""
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "workflow_id": self.workflow_id,
            "run_name": self.run_name,
            "status": self.status,
            "platform": self.platform,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            # Job search criteria
            "blacklist_companies": self.blacklist_companies or [],
            "location_preferences": self.location_preferences or "",
            "salary_range": self.salary_range or {},
            "job_types": self.job_types or [],
            "experience_level": self.experience_level,
            # Application settings
            "generate_cover_letter": self.generate_cover_letter,
            "send_connection_request": self.send_connection_request,
            "auto_apply": self.auto_apply,
            "submit_confident_application": self.submit_confident_application,
            "daily_application_limit": self.daily_application_limit,
            "selected_resume_id": (
                str(self.selected_resume_id) if self.selected_resume_id else None
            ),
            "selected_ats_template_id": self.selected_ats_template_id,
            "selected_cover_letter_template_id": self.selected_cover_letter_template_id,
            "use_ats_optimized": self.use_ats_optimized,
            "skip_previously_skipped_jobs": (
                self.skip_previously_skipped_jobs
                if self.skip_previously_skipped_jobs is not None
                else True
            ),
            "skip_staffing_companies": (
                self.skip_staffing_companies
                if self.skip_staffing_companies is not None
                else True
            ),
            # Advanced search
            "search_keywords": self.search_keywords or [],
            "exclude_keywords": self.exclude_keywords or [],
            "company_size_preference": self.company_size_preference,
            "industry_preferences": self.industry_preferences or [],
            "remote_preference": self.remote_preference,
            # Statistics
            "jobs_found": self.jobs_found or 0,
            "applications_sent": self.applications_sent or 0,
            "responses_received": self.responses_received or 0,
            "interviews_scheduled": self.interviews_scheduled or 0,
            # System fields
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "infinite_hunt_session_id": self.infinite_hunt_session_id,
            "config_reasoning_by_infinite_hunt": self.config_reasoning_by_infinite_hunt,
            "agent_run_template_id": self.agent_run_template_id,
            # NEW: Platform-specific filters
            "platform_filters": self.platform_filters,
            # Location and criteria (old fields for backward compatibility)
            "country": self.country,
            "salary_bound": self.salary_bound,
            "experience_levels": self.experience_levels or [],
            "remote_types": self.remote_types or [],
            "specific_locations": self.specific_locations or [],
            "semantic_instructions": self.semantic_instructions,
            "headless_on": self.headless_on,
        }

    def to_application_config(self) -> Dict[str, Any]:
        """Convert to application configuration format"""
        return {
            # Default from original config
            "skip_optional_questions": True,
            "show_browser": True,
            "auto_apply": self.auto_apply if self.auto_apply is not None else False,
            "submit_confident_application": False,  # Default
            "record_unseen_faqs_and_skip_application": True,
            "send_connection_to_hiring_team": (
                self.send_connection_request
                if self.send_connection_request is not None
                else False
            ),
            "generate_ats_optimized_resume": (
                self.use_ats_optimized if self.use_ats_optimized is not None else False
            ),
            "generate_cover_letter": (
                self.generate_cover_letter
                if self.generate_cover_letter is not None
                else True
            ),
            "daily_application_limit": (
                self.daily_application_limit
                if self.daily_application_limit is not None
                else 10
            ),
        }

    def to_filter_config(self) -> Dict[str, Any]:
        """
        Convert to filter configuration format with backward compatibility.

        Logic:
        1. If platform_filters exists and has data for the platform -> use it (NEW format)
        2. If platform_filters is NULL or empty -> use old columns (EXISTING records)

        This ensures ZERO impact on existing users!
        """
        # NEW: Check if we should use platform_filters
        if self.platform_filters and self.platform in self.platform_filters:
            # Use new platform_filters format
            platform_specific = self.platform_filters[self.platform]

            # Extract common filter fields from platform-specific filters
            return {
                "country": platform_specific.get("country", "usa"),
                "salary_bound": platform_specific.get("salary_bound"),
                "experience_levels": platform_specific.get("experience_levels", []),
                "remote_types": platform_specific.get("remote_types", []),
                "specific_locations": platform_specific.get("specific_locations", []),
                "semantic_instructions": self.semantic_instructions or "",
                # Common fields (not platform-specific)
                "job_types": self._extract_job_types(),
                "blacklist_companies": self._extract_blacklist_companies(),
            }

        # OLD: Fallback to old columns (for existing records with NULL platform_filters)
        # This is why existing users see NO CHANGE
        return {
            "country": self.country or "usa",
            "salary_bound": self.salary_bound,
            "experience_levels": self.experience_levels or [],
            "remote_types": self.remote_types or [],
            "job_types": self._extract_job_types(),
            "specific_locations": self.specific_locations or [],
            "blacklist_companies": self._extract_blacklist_companies(),
            "semantic_instructions": self.semantic_instructions or "",
        }

    def _extract_job_types(self) -> list:
        """Extract job_types - handle both direct arrays and JSONB format"""
        job_types_value = self.job_types
        if isinstance(job_types_value, list):
            return job_types_value
        elif isinstance(job_types_value, dict):
            return job_types_value.get("types", job_types_value.get("values", []))
        return []

    def _extract_blacklist_companies(self) -> list:
        """Extract blacklist_companies - handle both direct arrays and JSONB format"""
        blacklist_value = self.blacklist_companies
        if isinstance(blacklist_value, list):
            return blacklist_value
        elif isinstance(blacklist_value, dict):
            return blacklist_value.get("companies", blacklist_value.get("values", []))
        return []
