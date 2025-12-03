"""
Operation Activity Class for Workflow Execution
@file purpose: Defines the OperationActivity class for sequential operations
"""

from typing import Any, Dict

from pydantic import Field  # pylint: disable=import-error

from activity.base_activity import Activity, ActivityType


class OperationActivity(Activity):
    """Context information for an operation workflow step execution."""

    activity_type: ActivityType = ActivityType.ACTION
    next_activity_number: int = Field(default=-1, description="Next activity number")

    class Config:
        """Pydantic configuration."""

        validate_assignment = True
        extra = "forbid"

    def to_agent_instruction(self, inputs: Dict[str, Any] = None) -> str:
        """Convert to agent instruction with template rendering."""
        # Render the instruction and finish_condition with input variables
        rendered_instruction = self.render_template(self.instruction, inputs)
        rendered_finish_condition = self.render_template(self.finish_condition, inputs)

        return (
            f"Please do the following: {rendered_instruction}\n"
            "        The finish condition is: "
            f"{rendered_finish_condition}\n        "
        )
