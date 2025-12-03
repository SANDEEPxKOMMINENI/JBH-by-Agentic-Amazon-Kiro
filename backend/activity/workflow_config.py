"""
Simple Workflow Configuration
"""

import json
from pathlib import Path
from typing import Any, Dict

from activity.activity_factory import create_activities_from_json


class WorkflowConfig:
    """Simple workflow configuration from JSON."""  # noqa: E402

    def __init__(self, data: Dict[str, Any]):
        self.inputs = data.get("inputs", {})
        activities_data = data.get("activities", [])
        self.activities = create_activities_from_json(activities_data)

        # Auto-expand file paths and ensure they're available
        if (
            "available_file_paths" in self.inputs
            and self.inputs["available_file_paths"] is not None
        ):
            self.inputs["available_file_paths"] = [
                str(Path(path).expanduser())
                for path in self.inputs["available_file_paths"]
            ]

    @classmethod
    def from_json_file(cls, file_path: str):
        """Load from JSON file."""  # noqa: E402
        with open(file_path, "r") as f:
            data = json.load(f)
        return cls(data)
