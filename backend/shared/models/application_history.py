"""
Application History Models and Enums
@file purpose: Define data models and enums for application history tracking
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class ApplicationStatus(str, Enum):
    """Application status enum - matches v1 JobStatus values"""

    STARTED = "started"
    QUEUED = "queued"
    REMOVED = "removed"
    SKIPPED = "skipped"
    SUBMITTING = "submitting"
    FAILED = "failed"
    APPLIED = "applied"  # Default status for completed applications

    def __str__(self) -> str:
        """Return the string value of the enum"""
        return self.value

    @classmethod
    def get_all_statuses(cls):
        """Get all available status values as a list"""
        return [status.value for status in cls]

    @classmethod
    def is_valid_status(cls, status: str) -> bool:
        """Check if a given status string is valid"""
        return status in cls.get_all_statuses()


class ApplicationHistoryModel(BaseModel):
    """
    Complete Application History model matching current database schema
    Includes all existing fields plus new ATS example fields to be added

    🔗 SHARED ATTRIBUTES WITH ATSTemplateModel:
    The ATS analysis fields below mirror the example_* fields in
    ATSTemplateModel:
    - ats_score ↔ example_ats_score
    - ats_alignments ↔ example_ats_alignments
    - ats_keyword_to_add_to_resume ↔ example_ats_keyword_to_add_to_resume
    - optimized_ats_score ↔ example_optimized_ats_score
    - optimized_ats_alignments ↔ example_optimized_ats_alignments
    - missing_requirements ↔ example_missing_requirements
    - addressable_requirements ↔ example_addressable_requirements
    - skills_check_thinking ↔ example_skills_check_thinking
    """

    # Core identification (EXISTING)
    id: Optional[str] = None  # UUID primary key
    user_id: str
    workflow_run_id: Optional[str] = None
    ats_template_id: Optional[
        str
    ] = None  # Links to ATS template with additional experience
    resume_id: Optional[str] = None  # resume id
    cover_letter_id: Optional[str] = None  # Links to generated cover letter
    job_description_id: Optional[str] = None  # Links to shared job description
    status: Optional[str] = None  # Current status
    status_insight: Optional[str] = None  # Status explanation
    questions_and_answers: Optional[List[Dict[str, Any]]] = None  # Q&A

    # Job information (EXISTING)
    linkedin_job_id: Optional[str] = None  # LinkedIn job ID
    company_name: Optional[str] = None
    location: Optional[str] = None
    job_title: Optional[str] = None
    application_url: Optional[str] = None  # LinkedIn job URL
    post_time: Optional[str] = None
    hiring_team: Optional[Dict[str, Any]] = None  # Hiring manager/team info
    num_applicants: Optional[int] = None  # Number of applicants
    pos_context: Optional[str] = None  # Full job description/context
    application_datetime: Optional[datetime] = None  # When submitted

    # Job matching data (EXISTING)
    criteria_alignment: Optional[List[Dict[str, Any]]] = None  # Criteria

    # Timestamps (EXISTING)
    created_at: datetime
    updated_at: datetime

    # ========================================================
    # ATS Analysis Data
    # ========================================================

    # ATS Analysis Data - Initial (Before Optimization) (EXISTING)
    # 🔗 Mirrors: example_ats_score, example_ats_alignments,
    # example_ats_keyword_to_add_to_resume
    ats_score: Optional[int] = None  # Initial ATS score (0-100)
    ats_alignments: Optional[List[Dict[str, Any]]] = None  # Initial alignments
    ats_keyword_to_add_to_resume: Optional[List[str]] = None  # Keywords to add

    # ATS Analysis Data - Final (After Optimization) (EXISTING)
    # 🔗 Mirrors: example_optimized_ats_score, example_optimized_ats_alignments
    optimized_ats_score: Optional[int] = None  # ATS score after optimization
    optimized_ats_alignments: Optional[List[Dict[str, Any]]] = None  # Final

    # Skills Check Analysis (NEW)
    # 🔗 Mirrors: example_missing_requirements,
    # example_addressable_requirements, example_skills_check_thinking
    missing_requirements: Optional[List[Dict[str, Any]]] = None  # Not met
    addressable_requirements: Optional[List[Dict[str, Any]]] = None  # Can fix
    skills_check_thinking: Optional[str] = None  # AI reasoning

    # Resume Generation Analysis (NEW)
    ats_resume_id: Optional[str] = None  # Links to ATS resume
    optimized_resume_html: Optional[str] = None  # Generated HTML
    resume_generation_thinking: Optional[
        str
    ] = None  # AI thinking for resume generation

    # Contact Collection (NEW)
    contact_ids: Optional[list[str]] = None  # Array of contact UUIDs
    contact_collection_complete: Optional[bool] = None  # Collection status

    # Interview Tracking (NEW)
    interview_rounds: Optional[list[dict[str, Any]]] = None  # Rounds & notes

    class Config:
        """Pydantic configuration"""

        use_enum_values = True  # Use enum values instead of enum objects
        json_encoders = {datetime: lambda v: v.isoformat() if v else None}

    def to_dict(self) -> Dict[str, Any]:
        """Convert model to dictionary for database operations"""
        return self.dict(exclude_none=True)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ApplicationHistoryModel":
        """Create model instance from dictionary"""  # noqa: E402
        return cls(**data)


class ApplicationHistoryCreateRequest(BaseModel):
    """Request model for creating new application history entries"""

    user_id: str
    workflow_run_id: Optional[str] = None
    job_title: Optional[str] = None
    company_name: Optional[str] = None
    job_description: Optional[str] = None
    job_url: Optional[str] = None
    job_description_id: Optional[str] = None
    location: Optional[str] = None
    post_time: Optional[str] = None
    status: ApplicationStatus = ApplicationStatus.STARTED


class ApplicationHistoryUpdateRequest(BaseModel):
    """Request model for updating application history entries"""

    # Allow partial updates - all fields optional
    job_title: Optional[str] = None
    company_name: Optional[str] = None
    job_description: Optional[str] = None
    job_url: Optional[str] = None
    job_description_id: Optional[str] = None
    location: Optional[str] = None
    post_time: Optional[str] = None
    status: Optional[ApplicationStatus] = None
    application_datetime: Optional[datetime] = None
    resume_used: Optional[str] = None
    cover_letter_used: Optional[str] = None
    cover_letter_id: Optional[str] = None

    # ATS Analysis fields
    ats_score: Optional[int] = None
    ats_alignments: Optional[List[Dict[str, Any]]] = None
    ats_keyword_to_add_to_resume: Optional[List[str]] = None
    final_ats_score: Optional[int] = None
    final_ats_alignments: Optional[List[Dict[str, Any]]] = None
    missing_requirements: Optional[List[Dict[str, Any]]] = None
    addressable_requirements: Optional[List[Dict[str, Any]]] = None
    skills_check_thinking: Optional[str] = None
    ats_resume_id: Optional[str] = None
    ats_template_id: Optional[str] = None

    # Process fields
    application_method: Optional[str] = None
    application_notes: Optional[str] = None
    error_message: Optional[str] = None
    retry_count: Optional[int] = None

    # Contact Collection fields
    contact_ids: Optional[list[str]] = None
    contact_collection_complete: Optional[bool] = None

    # Interview Tracking fields
    interview_rounds: Optional[list[dict[str, Any]]] = None


class ApplicationHistoryResponse(BaseModel):
    """Response model for application history API endpoints"""

    success: bool
    message: Optional[str] = None
    data: Optional[ApplicationHistoryModel] = None
    total_count: Optional[int] = None  # For paginated responses


class ApplicationHistoryListResponse(BaseModel):
    """Response model for listing application history entries"""

    success: bool
    message: Optional[str] = None
    data: Optional[List[ApplicationHistoryModel]] = None
    total_count: Optional[int] = None
    page: Optional[int] = None
    page_size: Optional[int] = None
