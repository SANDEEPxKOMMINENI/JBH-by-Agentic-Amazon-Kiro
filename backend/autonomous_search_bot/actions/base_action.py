"""Base Action class for Autonomous Search Bot actions."""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict

logger = logging.getLogger(__name__)


class BaseAction(ABC):
    """
    Base class for all Autonomous Search Bot actions

    Provides common functionality and interface for all actions
    """

    def __init__(self, bot_instance):
        """
        Initialize action with bot instance

        Args:
            bot_instance: The AutonomousSearchBot instance
        """
        self.bot = bot_instance
        self.logger = logger

    @abstractmethod
    def execute(self, *args, **kwargs) -> Dict[str, Any]:
        """
        Execute the action

        Returns:
            Dict containing success status and relevant information
        """
        pass

    @property
    @abstractmethod
    def action_name(self) -> str:
        """Return the name of this action"""
        pass
