"""Additional info model for Supabase user_additional_info table."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class UserAdditionalInfo(BaseModel):
    """Represents user-authored long form fields used across automation."""

    id: UUID
    user_id: Optional[UUID] = None
    body: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
