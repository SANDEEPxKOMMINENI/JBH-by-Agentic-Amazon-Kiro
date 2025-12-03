"""
Activity Factory for creating activities from JSON data
@file purpose: Factory function to create appropriate activity instances
from JSON
"""

from typing import Any, Dict, Union

from activity.base_activity import ActivityType
from activity.decision_activity import DecisionActivity
from activity.operation_activity import OperationActivity


def create_activity_from_json(
    activity_data: Dict[str, Any],
) -> Union[OperationActivity, DecisionActivity]:
    """
    Create an activity instance from JSON data based on activity_type.  # noqa: E402

    Args:
        activity_data: Dictionary containing activity data from JSON  # noqa: E402

    Returns:
        Appropriate activity instance (OperationActivity or DecisionActivity)

    Raises:
        ValueError: If activity_type is not supported
        KeyError: If required fields are missing
    """
    activity_type = activity_data.get("activity_type")

    if not activity_type:
        raise KeyError("activity_type field is required in activity data")

    if activity_type == "operation":
        return OperationActivity(
            activity_number=activity_data["activity_number"],
            instruction=activity_data["instruction"],
            finish_condition=activity_data["finish_condition"],
            max_steps=activity_data.get("max_steps", 100),
            next_activity_number=activity_data.get("next_activity_number", -1),
        )

    if activity_type == "decision":
        return DecisionActivity(
            activity_number=activity_data["activity_number"],
            instruction=activity_data["instruction"],
            finish_condition=activity_data["finish_condition"],
            max_steps=activity_data.get("max_steps", 100),
            next_activity_number_options=activity_data["next_activity_number_options"],
            decision_instruction=activity_data["decision_instruction"],
        )

    raise ValueError(
        f"Unsupported activity_type: {activity_type}. Supported types: ['operation', 'decision']"
    )


def create_activities_from_json(activities_data: list) -> list:
    """
    Create a list of activity instances from JSON data.  # noqa: E402

    Args:
        activities_data: List of dictionaries containing activity data

    Returns:
        List of activity instances
    """
    activities = {}
    for activity_data in activities_data:
        try:
            activity = create_activity_from_json(activity_data)
            activities[activity.activity_number] = activity
        except (KeyError, ValueError) as e:
            activity_num = activity_data.get("activity_number", "unknown")
            raise ValueError(f"Error creating activity {activity_num}: {e}") from e

    return activities
