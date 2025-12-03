"""
Base Activity Class for Workflow Execution
@file purpose: Defines the base Activity class with common functionality
"""

from enum import Enum
from typing import Any, Dict

from jinja2 import Template  # pylint: disable=import-error
from pydantic import BaseModel, Field  # pylint: disable=import-error


class ActivityType(str, Enum):
    """Activity type matching frontend expectations."""

    ACTION = "action"
    THINKING = "thinking"
    RESULT = "result"


class Activity(BaseModel):
    """Base context information for a workflow step execution."""

    activity_type: ActivityType = Field(..., description="Activity type")
    activity_number: int = Field(..., description="Activity number in workflow")
    instruction: str = Field(..., description="Instruction for this activity")
    finish_condition: str = Field(..., description="Completion condition")
    max_steps: int = Field(default=100, description="Maximum steps allowed")

    def __str__(self) -> str:
        """String representation."""
        instruction_preview = self.instruction[:50]
        if len(self.instruction) > 50:
            instruction_preview += "..."
        return f"Activity {self.activity_number}: {instruction_preview}"

    class Config:
        """Pydantic configuration."""

        validate_assignment = True
        extra = "forbid"

    def render_template(
        self, template_string: str, inputs: Dict[str, Any] = None
    ) -> str:
        """Render a Jinja2 template with input variables."""
        if inputs is None:
            inputs = {}

        try:
            template = Template(template_string)
            return template.render(**inputs)
        except Exception:
            # If template rendering fails, return the original string
            # This provides backward compatibility for non-template instructions
            return template_string

    def to_agent_instruction(self, inputs: Dict[str, Any] = None) -> str:
        """Convert to agent instruction with template rendering."""
        raise NotImplementedError(
            "to_agent_instruction is not implemented for base activity"
        )
