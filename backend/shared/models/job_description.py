"""
Job Description Model
Represents shared job description data that can be referenced by multiple users
"""

from typing import List, Optional, Union

from pydantic import BaseModel


class HiringTeam(BaseModel):
    """Hiring team information from job posting"""

    name: Optional[str] = None
    about_text: Optional[str] = None
    linkedin_url: Optional[str] = None


class JobDescriptionModel(BaseModel):
    """
    Job Description Model - Shared job data across users

    This model represents job description data that is shared across multiple users.
    Multiple application_history records can reference the same job_description.
    """

    id: str
    linkedin_job_id: Optional[str] = None
    company_name: Optional[str] = None
    location: Optional[str] = None
    job_title: Optional[str] = None
    application_url: str
    post_time: Optional[str] = None
    hiring_team: Optional[HiringTeam] = None
    num_applicants: Optional[int] = 0
    pos_context: Optional[str] = None
    job_type: Optional[str] = None
    salary_range: Optional[Union[str, List[Union[int, float, str]]]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True


class JobDescriptionCreateRequest(BaseModel):
    """Request model for creating a job description"""

    id: str
    linkedin_job_id: Optional[str] = None
    company_name: Optional[str] = None
    location: Optional[str] = None
    job_title: Optional[str] = None
    application_url: str
    post_time: Optional[str] = None
    hiring_team: Optional[HiringTeam] = None
    num_applicants: Optional[int] = 0
    pos_context: Optional[str] = None
    job_type: Optional[str] = None
    salary_range: Optional[Union[str, List[Union[int, float, str]]]] = None  # noqa


class JobDescriptionUpdateRequest(BaseModel):
    """Request model for updating a job description (partial updates allowed)"""

    linkedin_job_id: Optional[str] = None
    company_name: Optional[str] = None
    location: Optional[str] = None
    job_title: Optional[str] = None
    post_time: Optional[str] = None
    hiring_team: Optional[HiringTeam] = None
    num_applicants: Optional[int] = None
    pos_context: Optional[str] = None
    job_type: Optional[str] = None
    salary_range: Optional[str] = None
