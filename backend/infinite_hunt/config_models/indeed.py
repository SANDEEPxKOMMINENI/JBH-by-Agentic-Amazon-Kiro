"""Pydantic model for Indeed bot configuration."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class IndeedFilters(BaseModel):
    date_posted: str = Field(
        "1",
        description="Indeed fromage filter (string days: '1','3','7','14')",
        pattern="^(1|3|7|14)$",
    )


class IndeedBotConfig(BaseModel):
    search_keywords: List[str] = Field(
        default_factory=list, description="Job titles/keywords for Indeed search"
    )
    location: Optional[str] = Field(None, description="Location string for Indeed")
    semantic_instructions: Optional[str] = None
    blacklist_companies: List[str] = Field(default_factory=list)
    platform_filters: IndeedFilters = Field(
        default_factory=IndeedFilters,
        description="Structured filters saved to workflow_runs.platform_filters.indeed",
    )
    skip_previously_skipped_jobs: bool = True
    skip_staffing_companies: bool = True
    generate_ats_optimized_resume: bool = False
    selected_resume_id: Optional[str] = None
    selected_ats_template_id: Optional[str] = None
    use_ats_optimized: bool = Field(
        False, description="Generate ATS-specific resumes during the run"
    )
