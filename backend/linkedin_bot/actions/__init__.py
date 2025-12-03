"""
LinkedIn Bot Actions Package
Contains modular action implementations for the LinkedIn bot
"""

from linkedin_bot.actions.base_action import BaseAction
from linkedin_bot.actions.collect_contacts_action import CollectContactsAction
from linkedin_bot.actions.connect_contacts_action import ConnectContactsAction
from linkedin_bot.actions.extract_job_data_action import ExtractJobDataAction
from linkedin_bot.actions.pause_hunting_action import PauseHuntingAction
from linkedin_bot.actions.resume_hunting_action import ResumeHuntingAction
from linkedin_bot.actions.start_hunting_action import StartHuntingAction  # noqa: E402
from linkedin_bot.actions.stop_collecting_contacts_action import (  # noqa: E402
    StopCollectingContactsAction,
)
from linkedin_bot.actions.stop_hunting_action import StopHuntingAction  # noqa: E402

__all__ = [
    "BaseAction",
    "CollectContactsAction",
    "ConnectContactsAction",
    "ExtractJobDataAction",
    "StartHuntingAction",
    "StopHuntingAction",
    "StopCollectingContactsAction",
    "PauseHuntingAction",
    "ResumeHuntingAction",
]
