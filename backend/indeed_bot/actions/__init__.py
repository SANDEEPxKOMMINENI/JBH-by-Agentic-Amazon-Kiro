#!/usr/bin/env python3
"""
Actions for Indeed Bot
"""

from indeed_bot.actions.pause_searching_action import PauseSearchingAction
from indeed_bot.actions.resume_searching_action import ResumeSearchingAction
from indeed_bot.actions.start_searching_action import StartSearchingAction
from indeed_bot.actions.stop_searching_action import StopSearchingAction

__all__ = [
    "StartSearchingAction",
    "StopSearchingAction",
    "PauseSearchingAction",
    "ResumeSearchingAction",
]
