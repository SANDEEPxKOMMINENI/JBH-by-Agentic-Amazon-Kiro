"""Controller for the Browser Use autonomous search agent."""

from __future__ import annotations

import asyncio
import logging
import re
import threading
from threading import Lock
from typing import Any, Dict, List, Optional

from autonomous_search_bot.autonomous_search_bot import AutonomousSearchBot
from services.llm_credential_manager import LLMCredentialManager

logger = logging.getLogger(__name__)


class AutonomousSearchController:
    def __init__(self) -> None:
        self.bots: Dict[str, AutonomousSearchBot] = {}
        self.activity_messages: Dict[str, List[Dict[str, Any]]] = {}
        self.polling_sessions: Dict[str, str] = {}
        self._message_lock = Lock()

    # ------------------------------------------------------------------
    def register_polling_session(self, workflow_run_id: str) -> None:
        self.polling_sessions[workflow_run_id] = workflow_run_id

    def unregister_polling_session(self, workflow_run_id: str) -> None:
        self.polling_sessions.pop(workflow_run_id, None)
        self.activity_messages.pop(workflow_run_id, None)

    def _queue_activity(self, workflow_run_id: str, payload: Dict[str, Any]) -> None:
        if workflow_run_id not in self.polling_sessions:
            return
        with self._message_lock:
            self.activity_messages.setdefault(workflow_run_id, []).append(payload)
            if len(self.activity_messages[workflow_run_id]) > 10_000:
                self.activity_messages[workflow_run_id] = self.activity_messages[
                    workflow_run_id
                ][-10_000:]

    # ------------------------------------------------------------------
    def start_autonomous_search(
        self,
        user_id: str,
        workflow_run_id: str,
        bot_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        try:
            if workflow_run_id in self.bots:
                bot = self.bots[workflow_run_id]
                if bot.status == "running":
                    return {
                        "success": False,
                        "message": "Autonomous bot already running for this session",
                    }
                self.bots.pop(workflow_run_id, None)

            self.register_polling_session(workflow_run_id)

            workflow_run_id = None
            custom_criteria = ""
            start_url = ""
            agent_instructions = ""
            max_jobs_per_platform = 10
            blacklist_companies: List[str] = []
            skip_staffing_companies = True

            generate_ats_resume = False
            ats_template_id = None
            llm_provider = None
            llm_api_key = None
            llm_model = None
            llm_endpoint = None
            max_running_time = 5  # Default 5 minutes
            resume_id = None
            use_vision = True

            if bot_config:
                workflow_run_id = bot_config.get("workflowRunId") or bot_config.get(
                    "agentRunId"
                )
                custom_criteria = bot_config.get("customCriteria", "")
                start_url = (
                    bot_config.get("startingUrl") or bot_config.get("startUrl") or ""
                )
                agent_instructions = bot_config.get("instructions") or bot_config.get(
                    "autonomousInstructions", ""
                )
                max_jobs_per_platform = bot_config.get("maxJobsPerPlatform", 10)
                generate_ats_resume = bot_config.get("generateATSResume", False)
                ats_template_id = bot_config.get("selectedATSTemplateId")
                llm_provider = bot_config.get("llmProvider")
                llm_api_key = bot_config.get("llmApiKey")
                llm_model = bot_config.get("llmModel")
                llm_endpoint = bot_config.get("llmEndpoint")
                max_running_time = bot_config.get("maxRunningTime")
                use_vision = bot_config.get("useVision", True)
                blacklist_companies = self._normalize_blacklist(
                    bot_config.get("blacklistCompanies")
                )
                skip_staffing_companies = bot_config.get("skipStaffingCompanies", True)
                resume_id = bot_config.get("resumeId") or bot_config.get(
                    "selectedResumeId"
                )

                # Load stored credentials if not provided in config
                if workflow_run_id and llm_provider:
                    if not llm_api_key or not llm_model:
                        stored = LLMCredentialManager.load_credentials(
                            workflow_run_id, llm_provider
                        )
                        if stored:
                            llm_api_key = llm_api_key or stored.get("api_key")
                            llm_model = llm_model or stored.get("model")
                            llm_endpoint = llm_endpoint or stored.get("endpoint")
                            logger.info(
                                f"Loaded stored credentials for {llm_provider} from local storage"
                            )

                    # Save new credentials for future use
                    elif llm_api_key and llm_model:
                        LLMCredentialManager.save_credentials(
                            workflow_run_id=workflow_run_id,
                            provider=llm_provider,
                            api_key=llm_api_key,
                            model=llm_model,
                            endpoint=llm_endpoint,
                        )

            def activity_callback(message: Dict[str, Any]) -> None:
                self._queue_activity(workflow_run_id, message)

            bot = AutonomousSearchBot(
                user_id=user_id,
                workflow_run_id=workflow_run_id,
                custom_criteria=custom_criteria,
                start_url=start_url,
                agent_instructions=agent_instructions,
                max_jobs=max_jobs_per_platform,
                blacklist_companies=blacklist_companies,
                skip_staffing_companies=skip_staffing_companies,
                resume_id=resume_id,
                activity_callback=activity_callback,
                generate_ats_resume=generate_ats_resume,
                ats_template_id=ats_template_id,
                llm_provider=llm_provider,
                llm_api_key=llm_api_key,
                llm_model=llm_model,
                llm_endpoint=llm_endpoint,
                max_running_time=max_running_time,
                use_vision=use_vision,
            )
            self.bots[workflow_run_id] = bot

            # Start the bot using the action pattern (like dice_bot)
            result = bot.start_searching()
            if not result.get("success"):
                return result

            loop = asyncio.new_event_loop()

            def run_bot() -> None:
                from autonomous_search_bot.actions import StartSearchingAction

                asyncio.set_event_loop(loop)
                try:
                    action = StartSearchingAction(bot)
                    loop.run_until_complete(action.execute())
                except Exception as exc:  # pragma: no cover - surfaced to UI
                    logger.exception("Autonomous bot crashed: %s", exc)
                    self._queue_activity(
                        workflow_run_id,
                        {
                            "type": "result",
                            "message": f"❌ Autonomous search failed: {exc}",
                            "thread_status": "failed",
                        },
                    )
                finally:
                    try:
                        loop.close()
                    finally:
                        self.bots.pop(workflow_run_id, None)
                        self.unregister_polling_session(workflow_run_id)

            threading.Thread(target=run_bot, daemon=True).start()

            return {
                "success": True,
                "message": "Autonomous search started",
            }
        except Exception as exc:
            logger.exception("Failed to start autonomous search: %s", exc)
            return {"success": False, "message": str(exc)}

    @staticmethod
    def _normalize_blacklist(value: Any) -> List[str]:
        if value is None:
            return []
        items: List[str] = []
        if isinstance(value, list):
            items = value
        elif isinstance(value, str):
            parts = re.split(r"[,\n;]", value)
            items = parts
        else:
            return []
        return [item.strip() for item in items if item and item.strip()]

    # ------------------------------------------------------------------
    def stop_autonomous_search(self, workflow_run_id: str) -> Dict[str, Any]:
        bot = self.bots.get(workflow_run_id)
        if not bot:
            return {"success": False, "message": "No autonomous bot found"}

        bot.stop()
        self.bots.pop(workflow_run_id, None)
        self.unregister_polling_session(workflow_run_id)
        self._queue_activity(
            workflow_run_id,
            {
                "type": "action",
                "message": "Autonomous search stopped",
                "thread_status": "stopped",
            },
        )
        return {"success": True, "message": "Autonomous bot stopped"}

    # ------------------------------------------------------------------
    def get_status(self, workflow_run_id: str) -> Dict[str, Any]:
        bot = self.bots.get(workflow_run_id)
        if not bot:
            return {
                "success": False,
                "message": "No autonomous bot active",
                "status": "idle",
            }
        return bot.get_status()


autonomous_search_controller = AutonomousSearchController()
