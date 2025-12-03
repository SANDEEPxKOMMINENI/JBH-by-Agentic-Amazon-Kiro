"""
Decision Activity Class for Workflow Execution
@file purpose: Defines the DecisionActivity class for conditional branching
"""

from typing import Any, Dict, List

from pydantic import BaseModel, Field  # pylint: disable=import-error

from activity.base_activity import Activity, ActivityType


class DecisionActivity(Activity):
    """Context information for a decision workflow step execution."""

    activity_type: ActivityType = ActivityType.ACTION
    next_activity_number_options: List[int] = Field(
        ..., description="List of possible next activity numbers based on decision"
    )
    decision_instruction: str = Field(
        ..., description="Instruction for making the decision"
    )

    class Config:
        """Pydantic configuration."""

        validate_assignment = True
        extra = "forbid"

    def to_agent_instruction(self, inputs: Dict[str, Any] = None) -> str:
        """Convert to agent instruction with template rendering."""
        # Render the instruction, finish_condition, and decision_instruction
        rendered_instruction = self.render_template(self.instruction, inputs)
        rendered_finish_condition = self.render_template(self.finish_condition, inputs)
        rendered_decision_instruction = self.render_template(
            self.decision_instruction, inputs
        )

        return (
            f"Please do the following: {rendered_instruction}\n"
            "        The finish condition is: "
            f"{rendered_finish_condition}\n"
            "        Lastly, you need to pick one of the following "
            f"activity numbers: {self.next_activity_number_options}\n"
            "        based on this instruction: "
            f"{rendered_decision_instruction}\n        "
        )


class DecisionActivityResult(BaseModel):
    """Result of a decision activity."""

    next_activity_number: int = Field(
        ..., description="Next activity number based on decision"
    )
    reason: str = Field(..., description="Reason for the decision")
