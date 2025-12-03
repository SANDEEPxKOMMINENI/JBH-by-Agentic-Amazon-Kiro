from dataclasses import dataclass
from typing import Dict


@dataclass
class JobData:
    """Data structure for job information."""

    job_title: str
    job_description: str
    company_name: str
    post_time: str
    location: str


@dataclass
class Interest:
    """Data structure for user's interests."""

    interest_description: str  # A text description of the user's interests


@dataclass
class InterestAlignment:
    """Data structure for interest alignment results."""

    criteria: str
    whether_aligned: bool

    def to_dict(self) -> Dict:
        """Convert the InterestAlignment object to a dictionary."""
        return {
            "aspect": self.criteria,
            "alignment": "✅ Yes" if self.whether_aligned else "❌ No",
        }
