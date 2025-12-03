"""
GeneratedCoverLetter model for Supabase generated_cover_letters table
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class GeneratedCoverLetter(BaseModel):
    """Model for public.generated_cover_letters table"""

    id: UUID
    user_id: UUID
    html_content: Optional[str] = None
    cover_letter_url: Optional[str] = None
    file_name: Optional[str] = None
    thinking: Optional[str] = None
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
            "html_content": self.html_content,
            "cover_letter_url": self.cover_letter_url,
            "file_name": self.file_name,
            "thinking": self.thinking,
            "created_at": (self.created_at.isoformat() if self.created_at else None),
            "updated_at": (self.updated_at.isoformat() if self.updated_at else None),
        }


class GeneratedCoverLetterCreate(BaseModel):
    """Model for creating new generated cover letters"""

    html_content: Optional[str] = None


class GeneratedCoverLetterUpdate(BaseModel):
    """Model for updating generated cover letters"""

    html_content: Optional[str] = None
