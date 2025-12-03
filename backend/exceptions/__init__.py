"""
Custom exceptions for JobHuntr backend
"""


class SubscriptionLimitException(Exception):
    """Exception raised when user has reached their subscription application limit"""

    def __init__(self, message: str, tier: str, limit: int, used: int, remaining: int):
        self.message = message
        self.tier = tier
        self.limit = limit
        self.used = used
        self.remaining = remaining
        super().__init__(self.message)

    def to_dict(self):
        """Convert exception details to dictionary for messaging"""
        return {
            "error_code": "SUBSCRIPTION_LIMIT_REACHED",
            "message": self.message,
            "tier": self.tier,
            "limit": self.limit,
            "used": self.used,
            "remaining": self.remaining,
        }


class DailyLimitException(Exception):
    """Exception raised when user has reached their daily application limit"""

    def __init__(
        self,
        message: str,
        daily_limit: int,
        daily_used: int,
        daily_remaining: int,
        next_reset: str,
    ):
        self.message = message
        self.daily_limit = daily_limit
        self.daily_used = daily_used
        self.daily_remaining = daily_remaining
        self.next_reset = next_reset
        super().__init__(self.message)

    def to_dict(self):
        """Convert exception details to dictionary for messaging"""
        return {
            "error_code": "DAILY_LIMIT_REACHED",
            "message": self.message,
            "daily_limit": self.daily_limit,
            "daily_used": self.daily_used,
            "daily_remaining": self.daily_remaining,
            "next_reset": self.next_reset,
        }


class AIResumeLimitException(Exception):
    """Exception raised when user has reached their AI resume generation limit"""

    def __init__(
        self,
        message: str,
        plan_tier: str,
        limit: int,
        current_usage: int,
    ):
        self.message = message
        self.plan_tier = plan_tier
        self.limit = limit
        self.current_usage = current_usage
        super().__init__(self.message)

    def to_dict(self):
        """Convert exception details to dictionary for messaging"""
        return {
            "error_code": "AI_RESUME_LIMIT_REACHED",
            "message": self.message,
            "current_tier": self.plan_tier,
            "limit": self.limit,
            "current_usage": self.current_usage,
            "call_to_action": "Upgrade your plan to generate more AI resumes.",
        }
