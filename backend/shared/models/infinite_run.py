"""Infinite hunt run configuration model."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class InfiniteRun(BaseModel):
    """Represents the persistent infinite hunt settings per user."""

    id: UUID
    user_id: UUID
    status: str = Field(default="idle")

    # Optional database columns
    selected_resume_id: Optional[UUID] = None
    selected_ats_template_id: Optional[UUID] = None
    selected_ordered_run_template_ids: Optional[List[UUID]] = None
    bot_blocked_run_template_ids: Optional[List[UUID]] = None
    last_run_id: Optional[UUID] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    use_ats_optimized: Optional[bool] = None
    session_id: Optional[UUID] = None
    semantic_instructions: Optional[str] = None
    headless_on: Optional[bool] = None
    auto_infinite_hunt_on: Optional[bool] = None

    class Config:
        from_attributes = True
