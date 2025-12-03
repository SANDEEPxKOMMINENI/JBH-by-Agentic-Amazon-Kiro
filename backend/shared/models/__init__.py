"""
Shared Pydantic models for Supabase database schemas
"""

from shared.models.agent_run_template import AgentRunTemplate
from shared.models.cover_letter_template import CoverLetterTemplate
from shared.models.generated_cover_letter import GeneratedCoverLetter
from shared.models.infinite_run import InfiniteRun
from shared.models.resume import Resume
from shared.models.user_additional_info import UserAdditionalInfo
from shared.models.user_faq import UserFaq
from shared.models.workflow_run import WorkflowRun

__all__ = [
    "AgentRunTemplate",
    "Resume",
    "UserFaq",
    "WorkflowRun",
    "CoverLetterTemplate",
    "GeneratedCoverLetter",
    "UserAdditionalInfo",
    "InfiniteRun",
]
