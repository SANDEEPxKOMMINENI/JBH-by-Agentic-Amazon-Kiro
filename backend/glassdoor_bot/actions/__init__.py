#!/usr/bin/env python3
"""
Actions for Glassdoor Bot
"""

from glassdoor_bot.actions.pause_searching_action import PauseSearchingAction
from glassdoor_bot.actions.resume_searching_action import ResumeSearchingAction
from glassdoor_bot.actions.start_searching_action import StartSearchingAction
from glassdoor_bot.actions.stop_searching_action import StopSearchingAction

__all__ = [
    "StartSearchingAction",
    "StopSearchingAction",
    "PauseSearchingAction",
    "ResumeSearchingAction",
]
