"""
AgentRunTemplate model for Supabase agent_run_templates table
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class AgentRunTemplate(BaseModel):
    """Represents an agent run template row from Supabase."""

    id: str
    name: str
    description: str
    require_sign_in: bool = True
    is_search_agent: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
