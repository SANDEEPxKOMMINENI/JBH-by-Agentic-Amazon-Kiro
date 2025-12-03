"""Pydantic model for LinkedIn bot configuration."""

from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field, model_validator


class LinkedInFilters(BaseModel):
    country: Optional[str] = Field(
        default=None, description="LinkedIn country filter code"
    )
    salary_bound: Optional[int] = Field(
        default=None, description="Minimum salary requirement in USD"
    )
    experience_levels: List[int] = Field(
        default_factory=list,
        description="LinkedIn experience level codes (1=Internship ... 6=Executive)",
    )
    remote_types: List[int] = Field(
        default_factory=list,
        description="LinkedIn remote preference codes (1=Remote,2=Hybrid,3=On-site)",
    )
    specific_locations: List[str] = Field(
        default_factory=list, description="Preferred metro areas or cities"
    )


class LinkedInBotConfig(BaseModel):
    search_keywords: str = Field(
        "",
        description="Job title/keyword used to seed LinkedIn search filters",
    )
    location_preferences: str = Field(
        "",
        description="Plain-text description of the preferred search location",
    )
    linkedin_starter_url: Optional[str] = Field(
        default=None, description="Optional pre-built search URL to open first"
    )
    semantic_instructions: Optional[str] = Field(
        default=None,
        description="Additional instructions passed to InterestMarker/LLM prompts",
    )
    blacklist_companies: List[str] = Field(
        default_factory=list, description="Companies to skip automatically"
    )
    auto_apply: bool = Field(
        False, description="Enable native LinkedIn EasyApply submissions"
    )
    generate_cover_letter: bool = Field(True, description="Generate cover letters")
    send_connection_request: bool = Field(
        False, description="Send connection requests to hiring team"
    )
    submit_confident_application: bool = Field(
        False, description="Require high-confidence signals before submission"
    )
    daily_application_limit: int | None = Field(
        default=10, ge=1, description="Upper bound for applications per batch"
    )
    skip_previously_skipped_jobs: bool = Field(
        True, description="Avoid jobs marked SKIPPED/REMOVED in history"
    )
    skip_staffing_companies: bool = Field(
        True, description="Ignore staffing agencies detected in job cards"
    )
    platform_filters: LinkedInFilters = Field(
        default_factory=LinkedInFilters,
        description="LinkedIn-specific filters - accepts nested {'linkedin': {...}} or flat structure",
    )
    selected_resume_id: Optional[str] = Field(
        default=None, description="Resume UUID to upload for applications"
    )
    selected_cover_letter_template_id: Optional[str] = Field(
        default=None, description="Cover letter template UUID, if any"
    )
    selected_ats_template_id: Optional[str] = Field(
        default=None, description="ATS resume template UUID"
    )
    use_ats_optimized: bool = Field(
        False, description="Generate ATS-specific resumes during the run"
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_platform_filters(cls, data: Any) -> Any:
        """
        Accept both nested and flat platform_filters structures.

        Service gateway sends: {"platform_filters": {"linkedin": {...}}}
        We need to unwrap the nested structure so Pydantic can parse the LinkedInFilters fields.
        """
        if isinstance(data, dict) and "platform_filters" in data:
            platform_filters = data["platform_filters"]

            # If nested with platform key, unwrap it
            if isinstance(platform_filters, dict) and "linkedin" in platform_filters:
                # Extract the linkedin-specific filters
                data["platform_filters"] = platform_filters["linkedin"]

        return data
