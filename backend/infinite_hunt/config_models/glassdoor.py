"""Pydantic model for Glassdoor bot configuration."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class GlassdoorBotConfig(BaseModel):
    search_keywords: List[str] = Field(default_factory=list)
    location: Optional[str] = None
    semantic_instructions: Optional[str] = None
    blacklist_companies: List[str] = Field(default_factory=list)
    skip_previously_skipped_jobs: bool = True
    skip_staffing_companies: bool = True
    generate_ats_optimized_resume: bool = False
    selected_resume_id: Optional[str] = None
    selected_ats_template_id: Optional[str] = None
    use_ats_optimized: bool = Field(
        False, description="Generate ATS-specific resumes during the run"
    )
    platform_filters: Dict[str, Any] = Field(
        default_factory=dict, description="Placeholder for future Glassdoor filters"
    )
