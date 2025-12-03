"""
Resume model for Supabase resumes table
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class Resume(BaseModel):
    """Model for public.resumes table"""

    id: UUID
    user_id: UUID
    file_name: str = Field(..., max_length=255)
    file_path: str = Field(..., max_length=500)
    blob_url: Optional[str] = Field(None, max_length=500)
    resume_text: Optional[str] = None
    resume_summary: Optional[Dict[str, Any]] = None
    blacklist_companies: Optional[List[str]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

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
            "file_name": self.file_name,
            "file_path": self.file_path,
            "blob_url": self.blob_url,
            "resume_content": self.resume_text,  # Map to expected field name
            "resume_summary": self.resume_summary or {},
            "blacklist_companies": self.blacklist_companies or [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
