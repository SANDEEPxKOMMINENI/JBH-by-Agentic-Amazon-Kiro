"""
Autonomous Browser Use powered job search agent
@file purpose: Browser-use agent that searches arbitrary job boards
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from browser_use import Agent, Browser, Tools

from shared.application_history_tracker import ApplicationHistoryTracker
from shared.langfuse_client import get_langfuse_client

logger = logging.getLogger(__name__)


class AutonomousSearchBot:
    """
    Autonomous Browser Use powered job search agent

    Features:
    - Uses browser_use library for AI-powered browser automation
    - Searches arbitrary job boards based on custom criteria
    - Saves promising jobs to JobHuntr queue
    - Supports multiple LLM providers (OpenAI, Azure, Claude, Gemini)
    """

    def __init__(
        self,
        user_id: str,
        workflow_run_id: str,
        custom_criteria: str,
        start_url: str,
        max_jobs: int = 10,
        agent_instructions: Optional[str] = None,
        resume_id: Optional[str] = None,
        blacklist_companies: Optional[List[str]] = None,
        skip_staffing_companies: bool = True,
        activity_callback=None,
        generate_ats_resume: bool = False,
        ats_template_id: Optional[str] = None,
        llm_provider: Optional[str] = None,
        llm_api_key: Optional[str] = None,
        llm_model: Optional[str] = None,
        llm_endpoint: Optional[str] = None,
        max_running_time: Optional[int] = None,
        use_vision: bool = True,
    ):
        self.workflow_run_id = workflow_run_id
        self.user_id = user_id
        self.custom_criteria = custom_criteria.strip()
        self.start_url = (start_url or "").strip()
        self.agent_instructions = (agent_instructions or "").strip()
        self.max_jobs_per_platform = max(1, max_jobs or 10)
        self.resume_id = resume_id
        sanitized_blacklist = [
            entry.strip()
            for entry in (blacklist_companies or [])
            if entry and entry.strip()
        ]
        self.blacklist_companies = sanitized_blacklist
        self.blacklist_company_lookup = {entry.lower() for entry in sanitized_blacklist}
        self.skip_staffing_companies = bool(skip_staffing_companies)
        self.generate_ats_resume = generate_ats_resume
        self.ats_template_id = ats_template_id
        self.llm_provider = llm_provider
        self.llm_api_key = llm_api_key
        self.llm_model = llm_model
        self.llm_endpoint = llm_endpoint
        self.max_running_time = max_running_time
        self.use_vision = True if use_vision is None else bool(use_vision)
        self.activity_callback = activity_callback

        # Browser-use components (initialized by action)
        self.tools: Optional[Tools] = None
        self.browser: Optional[Browser] = None
        self.agent: Optional[Agent] = None
        self.history = None
        self.llm = None

        # Bot state
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_requested = False
        self.status = "idle"
        self.jobs_saved = 0

        # Services
        self.application_history_tracker = ApplicationHistoryTracker(user_id)
        self.langfuse = get_langfuse_client()

    def stop(self) -> None:
        """Public stop hook invoked by the controller."""
        from autonomous_search_bot.actions import StopSearchingAction

        StopSearchingAction(self).execute()

    def start_searching(self) -> Dict[str, Any]:
        """Validate configuration before starting autonomous searching"""
        if self.status == "running":
            return {"success": False, "message": "Bot is already running"}

        if not self.llm_provider or not self.llm_api_key or not self.llm_model:
            return {"success": False, "message": "LLM configuration is required"}

        if self.llm_provider == "azure" and not self.llm_endpoint:
            return {"success": False, "message": "Azure OpenAI requires endpoint URL"}

        if not self.start_url:
            return {"success": False, "message": "Starting URL is required"}
        if not self.custom_criteria:
            return {"success": False, "message": "Search criteria are required"}

        return {"success": True, "message": "Autonomous search started"}

    def stop_searching(self) -> Dict[str, Any]:
        """Stop autonomous searching using StopSearchingAction"""
        from autonomous_search_bot.actions import StopSearchingAction

        action = StopSearchingAction(self)
        return action.execute()

    def get_status(self) -> Dict[str, Any]:
        """Get current bot status"""
        return {
            "success": True,
            "status": self.status,
            "jobs_saved": self.jobs_saved,
            "workflow_run_id": self.workflow_run_id,
        }
