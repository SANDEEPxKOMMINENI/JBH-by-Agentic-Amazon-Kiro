"""
Platform-specific filter enums and models
"""

from enum import Enum


class IndeedDatePostedEnum(str, Enum):
    """Date posted filter options for Indeed job search"""

    ANY = "any"  # Any time (default, no filter)
    ONE_DAY = "1"  # Last 24 hours
    THREE_DAYS = "3"  # Last 3 days
    SEVEN_DAYS = "7"  # Last 7 days
    FOURTEEN_DAYS = "14"  # Last 14 days


class GlassdoorDatePostedEnum(str, Enum):
    """Date posted filter options for Glassdoor job search"""

    ANY = "any"  # Any time (default, no filter)
    ONE_DAY = "1"  # Last 24 hours
    THREE_DAYS = "3"  # Last 3 days
    SEVEN_DAYS = "7"  # Last 7 days
    FOURTEEN_DAYS = "14"  # Last 14 days
    THIRTY_DAYS = "30"  # Last 30 days
