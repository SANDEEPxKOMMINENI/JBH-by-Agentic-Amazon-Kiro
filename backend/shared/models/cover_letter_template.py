"""
CoverLetterTemplate model for Supabase cover_letter_templates table
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class CoverLetterTemplate(BaseModel):
    """Model for public.cover_letter_templates table"""

    id: UUID
    user_id: UUID
    name: str = Field(..., max_length=255)
    html_content: Optional[str] = None  # Only saved from step 2 to step 3  # noqa: E402
    user_instruction: Optional[str] = None
    example_resume_id: Optional[UUID] = None
    example_ats_template_id: Optional[UUID] = None  # For future ATS templates
    example_job_url: Optional[str] = Field(None, max_length=500)
    example_job_description: Optional[str] = None
    example_cover_letter_result: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda dt: dt.isoformat() if dt else None,
            UUID: lambda uuid: str(uuid) if uuid else None,
        }

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses"""
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "name": self.name,
            "html_content": self.html_content,
            "user_instruction": self.user_instruction,
            "example_resume_id": (
                str(self.example_resume_id) if self.example_resume_id else None
            ),
            "example_ats_template_id": (
                str(self.example_ats_template_id)
                if self.example_ats_template_id
                else None
            ),
            "example_job_url": self.example_job_url,
            "example_job_description": self.example_job_description,
            "example_cover_letter_result": self.example_cover_letter_result,
            "created_at": (self.created_at.isoformat() if self.created_at else None),
            "updated_at": (self.updated_at.isoformat() if self.updated_at else None),
        }


class CoverLetterTemplateCreate(BaseModel):
    """Model for creating new cover letter templates"""

    name: str = Field(..., max_length=255)
    html_content: Optional[str] = None
    user_instruction: Optional[str] = None
    example_resume_id: Optional[UUID] = None
    example_ats_template_id: Optional[UUID] = None
    example_job_url: Optional[str] = Field(None, max_length=500)
    example_job_description: Optional[str] = None
    example_cover_letter_result: Optional[str] = None


class CoverLetterTemplateUpdate(BaseModel):
    """Model for updating cover letter templates"""

    name: Optional[str] = Field(None, max_length=255)
    html_content: Optional[str] = None
    user_instruction: Optional[str] = None
    example_resume_id: Optional[UUID] = None
    example_ats_template_id: Optional[UUID] = None
    example_job_url: Optional[str] = Field(None, max_length=500)
    example_job_description: Optional[str] = None
    example_cover_letter_result: Optional[str] = None
