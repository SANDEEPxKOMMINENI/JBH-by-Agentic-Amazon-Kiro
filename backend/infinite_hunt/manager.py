"""
Orchestration layer for the Infinite Hunt background loop.

The manager monitors Supabase for the user's infinite hunt settings, builds
agent run payloads from their most recent workflow configurations, and
sequentially launches the platform bots.  It keeps Supabase updated with the
active agent run ID so the desktop app can surface progress in real time.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import requests

from autonomous_search_bot.autonomous_search_bot import AutonomousSearchBot
from autonomous_search_bot.autonomous_search_controller import (
    autonomous_search_controller,
)
from constants import SERVICE_GATEWAY_URL
from dice_bot.dice_bot_controller import dice_bot_controller
from glassdoor_bot.glassdoor_bot_controller import glassdoor_bot_controller
from indeed_bot.indeed_bot_controller import indeed_bot_controller
from infinite_hunt.config_models import (
    AutonomousBotConfig,
    DiceBotConfig,
    GlassdoorBotConfig,
    IndeedBotConfig,
    LinkedInBotConfig,
    ZipRecruiterBotConfig,
)
from linkedin_bot.linkedin_bot_controller import linkedin_bot_controller
from services.jwt_token_manager import jwt_token_manager
from services.llm_credential_manager import LLMCredentialManager
from services.supabase_client import SupabaseClient, supabase_client
from shared.infinite_hunt_metadata import get_metadata_service
from ziprecruiter_bot.ziprecruiter_bot_controller import ziprecruiter_bot_controller

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Constants and helpers

LINKEDIN_WORKFLOWS = {"linkedin-apply", "linkedin-search"}

SUPPORTED_WORKFLOWS = {
    "linkedin-apply",
    "linkedin-search",
    "indeed-search",
    "ziprecruiter-search",
    "glassdoor-search",
    "dice-search",
    "autonomous-auto-search",
}

WORKFLOW_LABELS = {
    "linkedin-apply": "LinkedIn Auto Apply",
    "linkedin-search": "LinkedIn Auto Search",
    "indeed-search": "Indeed Auto Search",
    "ziprecruiter-search": "ZipRecruiter Auto Search",
    "glassdoor-search": "Glassdoor Auto Search",
    "dice-search": "Dice Auto Search",
    "autonomous-auto-search": "Autonomous Agent",
}


@dataclass
class AgentRunPlan:
    """Represents the configuration required to launch a workflow."""

    workflow_id: str
    run_name: str
    payload: dict[str, Any]
    platform_config: Any
    config_reasoning: Optional[str] = None


@dataclass
class InfiniteRunSettings:
    """User-level settings that apply across all generated runs."""

    resume_id: Optional[str]
    ats_template_id: Optional[str]
    use_ats_optimized: bool
    max_jobs_per_platform: int = 10
    semantic_instructions: str = ""
    headless_on: bool = False


# -----------------------------------------------------------------------------
# Agent run builder


class AgentRunBuilder:
    """Build new workflow run payloads from generated configs."""

    def __init__(
        self, settings: InfiniteRunSettings, session_id: Optional[str] = None
    ) -> None:
        self.settings = settings
        self._session_id = session_id

    def _apply_inherited_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Apply settings inherited from infinite hunt to the agent run payload.
        These settings override any AI-generated config values.
        """
        payload["selected_resume_id"] = self.settings.resume_id
        payload["selected_ats_template_id"] = self.settings.ats_template_id
        payload["use_ats_optimized"] = self.settings.use_ats_optimized
        payload["infinite_hunt_session_id"] = self._session_id
        payload["headless_on"] = self.settings.headless_on
        logger.info(
            f"Applied infinite_hunt_session_id to workflow run payload: {self._session_id}, "
            f"headless_on: {self.settings.headless_on}"
        )
        # Always override semantic instructions with the infinite run's instructions
        # This ensures the user's prompt ("what jobs are you looking for") is always used
        payload["semantic_instructions"] = self.settings.semantic_instructions
        return payload

    def build_plan(
        self, workflow_id: str, config: dict[str, Any], reasoning: Optional[str] = None
    ) -> Optional[AgentRunPlan]:
        try:
            if workflow_id in LINKEDIN_WORKFLOWS:
                model = LinkedInBotConfig(**config)
                payload = self._build_linkedin_payload(model)
            elif workflow_id == "indeed-search":
                model = IndeedBotConfig(**config)
                payload = self._build_indeed_payload(model)
            elif workflow_id == "ziprecruiter-search":
                model = ZipRecruiterBotConfig(**config)
                payload = self._build_zip_payload(model)
            elif workflow_id == "glassdoor-search":
                model = GlassdoorBotConfig(**config)
                payload = self._build_glassdoor_payload(model)
            elif workflow_id == "dice-search":
                model = DiceBotConfig(**config)
                payload = self._build_dice_payload(model)
            elif workflow_id == "autonomous-auto-search":
                model = AutonomousBotConfig(
                    workflow_run_id=f"infinite_autonomous_{uuid.uuid4().hex[:6]}",
                    **config,
                )
                payload = self._build_autonomous_payload(model)
            else:
                logger.warning("Unsupported workflow encountered: %s", workflow_id)
                return None
        except Exception as exc:
            logger.warning("Failed to build config for %s: %s", workflow_id, exc)
            return None

        run_name = self._make_run_name(workflow_id)
        payload.update(
            {
                "workflow_id": workflow_id,
                "run_name": run_name,
                "platform": self._infer_platform(workflow_id),
            }
        )

        # Add reasoning to payload if provided
        if reasoning:
            payload["config_reasoning_by_infinite_hunt"] = reasoning

        return AgentRunPlan(
            workflow_id=workflow_id,
            run_name=run_name,
            payload=payload,
            platform_config=model,
            config_reasoning=reasoning,
        )

    def _build_linkedin_payload(self, model: LinkedInBotConfig) -> dict[str, Any]:
        # Convert search_keywords string to list for DB storage
        search_keywords_list = [model.search_keywords] if model.search_keywords else []

        # platform_filters is always a LinkedInFilters object after model validation
        # Wrap it in nested structure for consistency across all platforms
        platform_filters = {"linkedin": model.platform_filters.model_dump()}

        payload = {
            "search_keywords": search_keywords_list,
            "location_preferences": model.location_preferences,
            "semantic_instructions": model.semantic_instructions,
            "blacklist_companies": model.blacklist_companies,
            "auto_apply": model.auto_apply,
            "generate_cover_letter": model.generate_cover_letter,
            "send_connection_request": model.send_connection_request,
            "submit_confident_application": True,
            "daily_application_limit": (model.daily_application_limit or 10),
            "skip_previously_skipped_jobs": (model.skip_previously_skipped_jobs),
            "skip_staffing_companies": (model.skip_staffing_companies),
            "platform_filters": platform_filters,
        }
        return self._apply_inherited_settings(payload)

    def _build_indeed_payload(self, model: IndeedBotConfig) -> dict[str, Any]:
        payload = {
            "search_keywords": model.search_keywords,
            "location_preferences": model.location,
            "semantic_instructions": model.semantic_instructions,
            "blacklist_companies": model.blacklist_companies,
            "skip_staffing_companies": (model.skip_staffing_companies),
            "skip_previously_skipped_jobs": (model.skip_previously_skipped_jobs),
            "platform_filters": {"indeed": model.platform_filters.model_dump()},
        }
        return self._apply_inherited_settings(payload)

    def _build_zip_payload(self, model: ZipRecruiterBotConfig) -> dict[str, Any]:
        payload = {
            "search_keywords": model.search_keywords,
            "location_preferences": model.location,
            "semantic_instructions": model.semantic_instructions,
            "blacklist_companies": model.blacklist_companies,
            "skip_staffing_companies": (model.skip_staffing_companies),
            "skip_previously_skipped_jobs": (model.skip_previously_skipped_jobs),
            "platform_filters": {"ziprecruiter": model.platform_filters},
        }
        return self._apply_inherited_settings(payload)

    def _build_glassdoor_payload(self, model: GlassdoorBotConfig) -> dict[str, Any]:
        payload = {
            "search_keywords": model.search_keywords,
            "location_preferences": model.location,
            "semantic_instructions": model.semantic_instructions,
            "blacklist_companies": model.blacklist_companies,
            "skip_staffing_companies": (model.skip_staffing_companies),
            "skip_previously_skipped_jobs": (model.skip_previously_skipped_jobs),
            "platform_filters": {"glassdoor": model.platform_filters},
        }
        return self._apply_inherited_settings(payload)

    def _build_dice_payload(self, model: DiceBotConfig) -> dict[str, Any]:
        payload = {
            "search_keywords": model.search_keywords,
            "location_preferences": model.location,
            "semantic_instructions": model.semantic_instructions,
            "blacklist_companies": model.blacklist_companies,
            "skip_staffing_companies": (model.skip_staffing_companies),
            "skip_previously_skipped_jobs": (model.skip_previously_skipped_jobs),
            "platform_filters": {"dice": model.platform_filters},
        }
        return self._apply_inherited_settings(payload)

    def _build_autonomous_payload(self, model: AutonomousBotConfig) -> dict[str, Any]:
        config = model.model_dump()
        config["session_id"] = model.session_id
        payload = {
            "semantic_instructions": model.custom_criteria,
            "platform_filters": {
                "autonomous": {
                    "platforms": model.platforms,
                    "instructions": model.agent_instructions,
                    "starting_url": model.starting_url,
                    "max_jobs_per_platform": model.max_jobs_per_platform
                    or self.settings.max_jobs_per_platform,
                    "llm_provider": model.llm_provider,
                    "llm_model": model.llm_model,
                    "llm_endpoint": model.llm_endpoint,
                    "use_vision": model.use_vision,
                    "max_running_time": model.max_running_time,
                    "metadata": model.metadata,
                }
            },
        }
        # Apply inherited settings first
        payload = self._apply_inherited_settings(payload)
        # Allow autonomous bot to override resume_id if specified in model
        if model.resume_id:
            payload["selected_resume_id"] = model.resume_id
        if model.selected_ats_template_id:
            payload["selected_ats_template_id"] = model.selected_ats_template_id
        return payload

    @staticmethod
    def _infer_platform(workflow_id: str) -> str:
        if workflow_id.startswith("linkedin"):
            return "linkedin"
        if workflow_id.startswith("indeed"):
            return "indeed"
        if workflow_id.startswith("ziprecruiter"):
            return "ziprecruiter"
        if workflow_id.startswith("glassdoor"):
            return "glassdoor"
        if workflow_id.startswith("dice"):
            return "dice"
        if workflow_id.startswith("autonomous"):
            return "autonomous"
        return "linkedin"

    @staticmethod
    def _make_run_name(workflow_id: str) -> str:
        label = WORKFLOW_LABELS.get(workflow_id, workflow_id.replace("-", " ").title())
        timestamp = datetime.now().strftime("%b %d, %H:%M")
        return f"[Infinite] {label} - {timestamp}"


# -----------------------------------------------------------------------------
# Infinite Hunt Manager


class InfiniteHuntManager:
    """Background monitor that continuously runs enabled workflows."""

    def __init__(
        self,
        supabase: SupabaseClient,
        poll_interval: float = 15.0,
        per_platform_delay: float = 5.0,
    ):
        self.supabase = supabase
        self.poll_interval = poll_interval
        self.per_platform_delay = per_platform_delay
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._active_agent_run_template_ids: list[str] = []
        self._active_user_id: Optional[str] = None
        self._current_status: Optional[str] = None
        self._current_run_id: Optional[str] = None
        self._current_agent_run_template_name: Optional[
            str
        ] = None  # agent_run_template_name of current run
        self._active_controller: Optional[Any] = None  # Active bot controller reference
        self._session_id: Optional[str] = None  # Infinite hunt session ID
        self._run_settings = InfiniteRunSettings(
            resume_id=None,
            ats_template_id=None,
            use_ats_optimized=False,
            semantic_instructions="",
        )
        self._instructions: str = ""

    # ------------------------------------------------------------------
    def _interruptible_sleep(self, duration: float) -> None:
        """
        Sleep for the specified duration, but check stop_event frequently.
        This allows the loop to exit quickly when stop() is called.
        """
        end_time = time.time() + duration
        while time.time() < end_time:
            if self._stop_event.is_set():
                return
            # Check every 0.5 seconds for responsiveness
            time.sleep(min(0.5, end_time - time.time()))

    def start(self) -> None:
        if self._monitor_thread and self._monitor_thread.is_alive():
            logger.debug("InfiniteHuntManager already running")
            return

        logger.info("Starting InfiniteHuntManager background thread")
        self._stop_event.clear()
        self._monitor_thread = threading.Thread(
            target=self._run_loop,
            name="InfiniteHuntMonitor",
            daemon=True,
        )
        self._monitor_thread.start()

    def stop(self) -> None:
        logger.info("Stopping InfiniteHuntManager background thread")
        self._stop_event.set()
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5)
        self._current_status = None
        self._current_run_id = None
        self._current_agent_run_template_name = None
        self._active_controller = None

        # Update metadata service
        metadata_service = get_metadata_service()
        metadata_service.stop_infinite_hunt()

    def get_active_run(self) -> Optional[tuple[str, str]]:
        """
        Get the currently active workflow run.
        Returns: (workflow_run_id, workflow_id) or None if no active run
        """
        if self._current_run_id and self._current_agent_run_template_name:
            return (self._current_run_id, self._current_agent_run_template_name)
        return None

    def get_active_controller(self) -> Optional[tuple[Any, str, str]]:
        """
        Get the currently active bot controller and run info.
        Returns: (controller, workflow_run_id, workflow_id) or None if no active controller
        """
        if (
            self._active_controller
            and self._current_run_id
            and self._current_agent_run_template_name
        ):
            return (
                self._active_controller,
                self._current_run_id,
                self._current_agent_run_template_name,
            )
        return None

    def _get_controller_for_workflow(self, workflow_id: str) -> Optional[Any]:
        """Get the appropriate bot controller for a given workflow ID"""
        if workflow_id in LINKEDIN_WORKFLOWS:
            return linkedin_bot_controller
        elif workflow_id == "indeed-search":
            return indeed_bot_controller
        elif workflow_id == "ziprecruiter-search":
            return ziprecruiter_bot_controller
        elif workflow_id == "glassdoor-search":
            return glassdoor_bot_controller
        elif workflow_id == "dice-search":
            return dice_bot_controller
        elif workflow_id == "autonomous-auto-search":
            return autonomous_search_controller
        else:
            logger.warning(f"No controller found for workflow: {workflow_id}")
            return None

    # ------------------------------------------------------------------
    def _run_loop(self) -> None:
        """Main background loop that monitors status and executes workflows."""
        logger.info("Infinite hunt background loop started")

        # Generate a new session ID for this infinite hunt run
        new_session_id = str(uuid.uuid4())
        logger.info(f"Generated new infinite hunt session ID: {new_session_id}")

        # Update metadata service - this is the first-hand source of truth
        metadata_service = get_metadata_service()
        metadata_service.start_infinite_hunt(new_session_id)

        # Write the new session ID to the database
        self.supabase.update_infinite_run_state(
            status="running", session_id=new_session_id
        )

        while not self._stop_event.is_set():
            try:
                # Skip if a workflow run is currently executing
                if self._current_run_id is not None:
                    logger.debug(
                        f"Workflow run {self._current_run_id} still in progress, waiting..."
                    )
                    self._interruptible_sleep(self.poll_interval)
                    continue

                run_record = self.supabase.get_infinite_run()
                if not run_record:
                    logger.warning(
                        "No infinite hunt configuration found, stopping loop"
                    )
                    self._current_status = None
                    # Set status to stopped if no config
                    self.supabase.update_infinite_run_state(status="stopped")
                    break

                self._update_run_settings(run_record)

                # Update database to confirm we're running
                logger.info("Updating infinite hunt status to running in database")
                self.supabase.update_infinite_run_state(status="running")

                # Execute workflow cycle
                logger.info("Starting workflow cycle execution")
                self._execute_workflow_cycle()
                logger.info("Workflow cycle completed, continuing loop")

            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("Infinite hunt loop crashed: %s", exc)
                # Set status to stopped on critical error
                try:
                    self.supabase.update_infinite_run_state(status="stopped")
                except Exception:
                    pass
                self._interruptible_sleep(self.poll_interval)

        logger.info("Infinite hunt background loop exited")

    def _validate_template_ids(self, template_ids: list[str]) -> list[str]:
        """
        Validate that template IDs exist in the database.
        Returns only valid template IDs, filtering out deleted ones.
        """
        if not template_ids:
            return []

        import requests  # noqa: E402

        from services.jwt_token_manager import jwt_token_manager  # noqa: E402

        try:
            # Get JWT token for authentication
            token = jwt_token_manager.get_token()
            if not token:
                logger.warning("No JWT token available for template validation")
                # Return all IDs if we can't validate - fail gracefully later
                return template_ids

            headers = {"Authorization": f"Bearer {token}"}

            # Fetch all templates via service-gateway in one API call
            url = f"{SERVICE_GATEWAY_URL.rstrip('/')}/api/agent-run-templates/"
            response = requests.get(url, headers=headers, timeout=10)

            if response.status_code != 200:
                logger.error(
                    f"Failed to fetch templates from service-gateway: {response.status_code}, "
                    f"Response: {response.text}"
                )
                # Return all IDs if fetch fails - fail gracefully later
                return template_ids

            # Extract existing template IDs
            templates = response.json()
            logger.debug(f"Fetched {len(templates)} templates from service-gateway")

            existing_ids = {template["id"] for template in templates}

            # Filter template_ids to only include existing ones
            logger.debug(f"Looking for template IDs: {template_ids}")
            valid_ids = []
            for template_id in template_ids:
                if str(template_id) in existing_ids:
                    valid_ids.append(template_id)
                    logger.debug(f"Template {template_id} exists")
                else:
                    logger.warning(
                        f"Template {template_id} not found in database (deleted?), skipping"
                    )

            return valid_ids

        except Exception as e:
            logger.error(f"Error validating templates: {e}")
            # Return all IDs if validation fails - better to fail gracefully later
            return template_ids

    def _update_run_settings(self, run_record) -> None:
        """Update internal state from the run record."""
        self._active_user_id = str(run_record.user_id)
        self._session_id = run_record.session_id  # Infinite hunt session ID
        logger.info(
            f"Updated infinite hunt session_id from database: {self._session_id}"
        )

        # Validate template IDs - filter out any that don't exist
        raw_template_ids = run_record.selected_ordered_run_template_ids or []
        self._active_agent_run_template_ids = self._validate_template_ids(
            raw_template_ids
        )

        if len(self._active_agent_run_template_ids) < len(raw_template_ids):
            removed_count = len(raw_template_ids) - len(
                self._active_agent_run_template_ids
            )
            logger.warning(
                f"Filtered out {removed_count} invalid/deleted template(s). "
                f"Valid templates: {self._active_agent_run_template_ids}"
            )

        self._instructions = (run_record.semantic_instructions or "").strip()
        self._run_settings = InfiniteRunSettings(
            resume_id=run_record.selected_resume_id,
            ats_template_id=run_record.selected_ats_template_id,
            use_ats_optimized=bool(getattr(run_record, "use_ats_optimized", False)),
            semantic_instructions=self._instructions,
            headless_on=bool(getattr(run_record, "headless_on", False)),
        )

    def _execute_workflow_cycle(self) -> None:
        """Execute one complete cycle through all configured workflows."""
        if not self._active_agent_run_template_ids:
            logger.warning(
                "Infinite hunt running without any workflows selected. "
                "Waiting for config."
            )
            self._interruptible_sleep(self.poll_interval)
            return

        builder = AgentRunBuilder(self._run_settings, self._session_id)

        for active_agent_run_template_id in list(self._active_agent_run_template_ids):
            self.current_agent_run_template_id = active_agent_run_template_id
            if self._stop_event.is_set():
                logger.info("Stop event detected, breaking workflow cycle")
                break

            # Give some time for db to update to running
            self._interruptible_sleep(self.per_platform_delay)

            # Check if status changed (e.g., stopped, paused) mid-cycle
            current_record = self.supabase.get_infinite_run()
            current_status = (
                (current_record.status or "").lower() if current_record else ""
            )
            if not current_record or current_status != "running":
                logger.info(
                    "Infinite hunt status changed mid-cycle, "
                    "stopping workflow execution"
                )
                # Stop the currently active bot if there is one
                self._stop_active_bot()
                break

            # Update status to show we're running
            self.supabase.update_infinite_run_state(status="running")

            # Generate config for this workflow template ID
            agent_run_config, thinking = self._generate_agent_run_config(
                active_agent_run_template_id
            )
            if not agent_run_config:
                logger.warning(
                    "No configuration available for %s. Skipping.",
                    active_agent_run_template_id,
                )
                self._interruptible_sleep(self.poll_interval)
                continue

            # Extract workflow_id from the config
            agent_run_template_name = agent_run_config.get("workflow_id")

            plan_uploaded_to_db = builder.build_plan(
                agent_run_template_name, agent_run_config, thinking
            )
            if not plan_uploaded_to_db:
                logger.warning(
                    f"Skipping {active_agent_run_template_id}: unable to build run payload."
                )
                continue

            # Add agent_run_template_id to the payload
            plan_uploaded_to_db.payload[
                "agent_run_template_id"
            ] = active_agent_run_template_id

            # Update status before starting execution
            self.supabase.update_infinite_run_state(status="running")

            self._execute_single_agent_run(agent_run_template_name, plan_uploaded_to_db)
            if self._stop_event.is_set():
                logger.info(
                    "Stop event detected after workflow execution, breaking cycle"
                )
                break
            self._interruptible_sleep(self.per_platform_delay)

        if not self._stop_event.is_set():
            # Leave status as-is; frontend polls service-gateway for status.
            self.supabase.update_infinite_run_state()

    def _generate_agent_run_config(
        self, agent_run_template_id: str
    ) -> tuple[dict[str, Any], str]:
        """
        Call service gateway to generate workflow configs via AI.
        Returns tuple of (config, thinking).
        """
        if not agent_run_template_id:
            return {}, ""

        instructions = self._instructions or ""
        if not instructions.strip():
            instructions = (
                "Find high-signal roles that match the user's "
                "resume and preferences."
            )

        payload: dict[str, Any] = {
            "instructions": instructions,
            # Ensure UUIDs are serialized as strings for JSON payload
            "agent_run_template_id": str(agent_run_template_id),
        }
        # Pass session_id to filter statistics by this infinite hunt session
        if self._session_id is not None:
            payload["session_id"] = str(self._session_id)
        if self._run_settings.resume_id is not None:
            payload["resume_id"] = str(self._run_settings.resume_id)
        if self._run_settings.ats_template_id is not None:
            payload["ats_template_id"] = str(self._run_settings.ats_template_id)
        if self._run_settings.use_ats_optimized is not None:
            payload["use_ats_optimized"] = self._run_settings.use_ats_optimized

        try:
            url = (
                f"{SERVICE_GATEWAY_URL.rstrip('/')}/"
                "api/infinite-runs/generate-config"
            )
            token = jwt_token_manager.get_token()
            headers = {}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            else:
                logger.warning("No JWT token available for config generation")

            response = requests.post(url, json=payload, headers=headers, timeout=30)

            if response.status_code != 200:
                logger.error(
                    "Failed to generate workflow configs: %s - %s",
                    response.status_code,
                    response.text,
                )
                return {}, ""

            data = response.json() or {}
            raw_configs = data.get("workflow_configs")
            if not isinstance(raw_configs, dict) or not raw_configs:
                logger.warning(
                    "Unexpected config response format: %s", type(raw_configs)
                )
                return {}, ""

            # Service gateway returns a single config keyed by agent_run_template_id.
            template_key = str(agent_run_template_id)
            config_data = raw_configs.get(template_key)
            if config_data is None:
                # Fallback: take the first entry if key mismatch
                _, config_data = next(iter(raw_configs.items()))

            if not isinstance(config_data, dict):
                logger.warning(
                    "Unexpected config data format for %s: %s",
                    template_key,
                    type(config_data),
                )
                return {}, ""

            # New format with thinking: {"config": {...}, "thinking": "..."}
            if "config" in config_data:
                config = config_data["config"]
                thinking = config_data.get("thinking", "")

                # Pretty print config and thinking to logger
                import json

                logger.info(
                    "\n=== Generated Config for %s ===\n"
                    "Thinking: %s\n"
                    "\nConfig:\n%s\n"
                    "================================",
                    template_key,
                    thinking,
                    json.dumps(config, indent=2),
                )

                platform = config.get("platform", "unknown")
                search_keywords = config.get("search_keywords", [])
                platform_filters = config.get("platform_filters", {})

                logger.info(
                    "Config Summary - Platform: %s | Keywords: %s | Filters: %s",
                    platform,
                    search_keywords,
                    json.dumps(platform_filters, indent=2),
                )

                return config, thinking

            # Old format - direct config dict
            return config_data, ""
        except Exception as exc:
            logger.exception("Failed to generate workflow configs: %s", exc)
            return {}, ""

    # ------------------------------------------------------------------
    def _execute_single_agent_run(
        self, agent_run_template_name: str, plan: AgentRunPlan
    ) -> None:
        """Execute a single agent run and update status."""
        label = WORKFLOW_LABELS.get(agent_run_template_name, agent_run_template_name)
        # Log the agent_run_template_id before creating workflow run
        logger.info(
            f"Creating workflow run with agent_run_template_id: {plan.payload.get('agent_run_template_id')}"
        )
        run = self.supabase.create_workflow_run(plan.payload)
        if not run:
            logger.error(
                f"Failed to create an agent run for {label}. "
                "Is the service gateway reachable?"
            )
            return

        run_id = str(run.id)
        self._current_run_id = run_id
        self._current_agent_run_template_name = agent_run_template_name

        # Update metadata service with new agent run
        metadata_service = get_metadata_service()
        platform = AgentRunBuilder._infer_platform(agent_run_template_name)
        metadata_service.start_agent_run(run_id, agent_run_template_name, platform)

        # Cache the controller for this workflow
        self._active_controller = self._get_controller_for_agent_run_template(
            agent_run_template_name
        )

        try:
            # Register this workflow run for activity polling in bot controller
            self._register_for_polling(agent_run_template_name, run_id)

            # Update workflow run status to "running"
            self.supabase.update_workflow_run_status(
                run_id, "running", started_at=datetime.utcnow().isoformat()
            )

            # Keep database status in sync; last_run_id is updated on completion.
            self.supabase.update_infinite_run_state(status="running")

            # Launch bot (returns immediately, bot runs in background thread)
            success, detail = self._launch_bot(agent_run_template_name, run_id, plan)

            if not success:
                # Bot failed to start, mark as failed and cleanup
                self.supabase.update_workflow_run_status(
                    run_id, "failed", completed_at=datetime.utcnow().isoformat()
                )
                self.supabase.update_infinite_run_state(status="stopped")
                self._unregister_from_polling(agent_run_template_name, run_id)
                # Update metadata service
                metadata_service.fail_agent_run(run_id)
                return

            # Bot started successfully - auto-unblock this template if it was blocked
            agent_run_template_id = plan.payload.get("agent_run_template_id")
            if agent_run_template_id:
                self.supabase.unblock_template(str(agent_run_template_id))
                logger.info(
                    f"Template {agent_run_template_id} auto-unblocked on successful "
                    "bot start"
                )

            # Bot started successfully, now wait for it to complete
            logger.info(f"Bot launched for {label}, waiting for completion...")
            verification_required = self._wait_for_bot_completion(
                agent_run_template_name, run_id
            )

            # Check if bot was stopped due to verification requirement
            if verification_required:
                logger.warning(
                    f"Bot {run_id} stopped due to verification requirement. "
                    f"Blocking template {agent_run_template_name}."
                )
                # Get the agent_run_template_id from plan payload
                agent_run_template_id = plan.payload.get("agent_run_template_id")
                if agent_run_template_id:
                    self.supabase.block_template(str(agent_run_template_id))
                    logger.info(
                        f"Template {agent_run_template_id} blocked due to "
                        "verification requirement"
                    )

                # Mark as stopped (not completed) due to verification
                self.supabase.update_workflow_run_status(
                    run_id, "stopped", completed_at=datetime.utcnow().isoformat()
                )
                self.supabase.update_infinite_run_state(last_run_id=run_id)
                metadata_service.fail_agent_run(run_id)
            else:
                # Bot completed normally, update status
                self.supabase.update_workflow_run_status(
                    run_id, "completed", completed_at=datetime.utcnow().isoformat()
                )
                self.supabase.update_infinite_run_state(last_run_id=run_id)
                metadata_service.complete_agent_run(run_id)

            # Unregister after completion
            self._unregister_from_polling(agent_run_template_name, run_id)
        except Exception as exc:
            # Ensure cleanup happens even if an exception occurs
            logger.exception(
                f"Error executing workflow {agent_run_template_name}: {exc}"
            )
            try:
                self._unregister_from_polling(agent_run_template_name, run_id)
            except Exception:
                pass  # Best effort cleanup
        finally:
            # Always clear the current run ID, workflow ID, and controller
            self._current_run_id = None
            self._current_agent_run_template_name = None
            self._active_controller = None

    def _wait_for_bot_completion(
        self, agent_run_template_name: str, run_id: str
    ) -> bool:
        """Wait indefinitely for the bot to complete by checking the bot controller.

        Returns:
            True if bot requires verification (was blocked by Cloudflare), False otherwise.
        """
        check_interval = 2  # Check every 2 seconds
        elapsed_time = 0
        bot_found = False  # Track if bot exists in controller
        has_bot_ever_started = False  # Track if bot.is_running was ever True
        verification_required = False  # Track if bot was blocked by verification

        # Get the appropriate controller for this workflow
        controller = self._get_controller_for_agent_run_template(
            agent_run_template_name
        )
        if not controller:
            logger.warning(
                f"No controller found for workflow {agent_run_template_name}, "
                "skipping wait"
            )
            return False

        logger.info(f"Waiting for bot {run_id} to complete (no timeout)...")

        # Initial delay to avoid race condition where we check before bot thread sets is_running=True
        time.sleep(0.5)

        while True:  # Wait indefinitely until bot completes or stop event
            # Check if stop event is set
            if self._stop_event.is_set():
                logger.info(f"Stop event set, stopping active bot for run {run_id}")
                self._stop_active_bot()
                break

            # Check bot's current running state
            is_bot_running_now = False
            try:
                # All bot controllers use a "bots" dictionary mapping workflow_run_id -> bot instance
                if hasattr(controller, "bots") and run_id in controller.bots:
                    bot_found = True  # We found the bot in the controller
                    bot = controller.bots.get(run_id)
                    if bot:
                        is_bot_running_now = getattr(bot, "is_running", False)
                        logger.debug(
                            f"Bot {run_id} status: is_running={is_bot_running_now}"
                        )

                        # Remember if bot has ever entered running state
                        if is_bot_running_now:
                            has_bot_ever_started = True

                        # Check if bot was stopped due to verification
                        if getattr(bot, "verification_required", False):
                            verification_required = True
                else:
                    # Log when bot is not found in controller
                    if elapsed_time % 30 == 0:  # Log every 30 seconds
                        logger.warning(
                            f"Bot {run_id} not found in controller after "
                            f"{elapsed_time}s. "
                            f"Has controller.bots: {hasattr(controller, 'bots')}, "
                            f"Bot in controller: "
                            f"{run_id in getattr(controller, 'bots', {})}"
                        )

                # Periodic status update
                if elapsed_time > 0 and elapsed_time % 30 == 0:  # Every 30 seconds
                    logger.info(
                        f"Waiting for bot {run_id} ({elapsed_time}s elapsed). "
                        f"Found: {bot_found}, Started: {has_bot_ever_started}, "
                        f"Running now: {is_bot_running_now}"
                    )

                # Bot is completed when:
                # 1. Bot exists in controller AND
                # 2. Bot has started running (was True at some point) AND
                # 3. Bot is no longer running (is False now)
                # This prevents early exit before bot thread starts
                if bot_found and has_bot_ever_started and not is_bot_running_now:
                    # Final check for verification_required flag
                    if bot and getattr(bot, "verification_required", False):
                        verification_required = True
                    logger.info(
                        f"Bot {run_id} completed. "
                        f"verification_required={verification_required}"
                    )
                    break

            except Exception as exc:
                logger.warning(f"Error checking bot status: {exc}")
                # Only break on error if bot had started, otherwise keep waiting
                if bot_found and has_bot_ever_started:
                    break

            # Sleep and increment elapsed time
            time.sleep(check_interval)
            elapsed_time += check_interval

        return verification_required

    def _stop_active_bot(self) -> None:
        """Stop the currently active bot if there is one."""
        if not self._current_run_id or not self._current_agent_run_template_name:
            logger.debug("No active bot to stop")
            return

        run_id = self._current_run_id
        workflow_id = self._current_agent_run_template_name

        logger.info(f"Stopping active bot for workflow run {run_id} ({workflow_id})")

        try:
            controller = self._get_controller_for_workflow(workflow_id)
            if not controller:
                logger.warning(f"No controller found for workflow {workflow_id}")
                return

            # All controllers use bots dictionary
            if hasattr(controller, "bots") and run_id in controller.bots:
                bot = controller.bots.get(run_id)
                if bot and hasattr(bot, "stop_searching"):
                    logger.info(f"Calling stop_searching on bot {run_id}")
                    bot.stop_searching()
                elif bot:
                    # Fallback: set is_running to False
                    logger.info(f"Setting is_running=False on bot {run_id}")
                    bot.is_running = False
            else:
                logger.warning(f"No bot found in controller for run {run_id}")

            # Update workflow run status to stopped
            self.supabase.update_workflow_run_status(
                run_id, "stopped", completed_at=datetime.utcnow().isoformat()
            )
        except Exception as exc:
            logger.exception(f"Error stopping active bot {run_id}: {exc}")

    def _get_controller_for_agent_run_template(self, agent_run_template_name: str):
        """Get the bot controller for a given agent run template name."""
        if agent_run_template_name in LINKEDIN_WORKFLOWS:
            return linkedin_bot_controller
        elif agent_run_template_name == "indeed-search":
            return indeed_bot_controller
        elif agent_run_template_name == "ziprecruiter-search":
            return ziprecruiter_bot_controller
        elif agent_run_template_name == "glassdoor-search":
            return glassdoor_bot_controller
        elif agent_run_template_name == "dice-search":
            return dice_bot_controller
        elif agent_run_template_name == "autonomous-auto-search":
            return autonomous_search_controller
        return None

    def _register_for_polling(self, agent_run_template_name: str, run_id: str) -> None:
        """Register workflow run for activity polling with bot controller"""
        if agent_run_template_name in LINKEDIN_WORKFLOWS:
            linkedin_bot_controller.register_polling_session(run_id)
        elif agent_run_template_name == "indeed-search":
            indeed_bot_controller.register_polling_session(run_id)
        elif agent_run_template_name == "ziprecruiter-search":
            ziprecruiter_bot_controller.register_polling_session(run_id)
        elif agent_run_template_name == "glassdoor-search":
            glassdoor_bot_controller.register_polling_session(run_id)
        elif agent_run_template_name == "dice-search":
            dice_bot_controller.register_polling_session(run_id)
        elif agent_run_template_name == "autonomous-auto-search":
            autonomous_search_controller.register_polling_session(run_id)
        logger.info(f"Registered {agent_run_template_name} for polling: {run_id}")

    def _unregister_from_polling(
        self, agent_run_template_name: str, run_id: str
    ) -> None:
        """Unregister workflow run from activity polling"""
        if agent_run_template_name in LINKEDIN_WORKFLOWS:
            linkedin_bot_controller.unregister_polling_session(run_id)
        elif agent_run_template_name == "indeed-search":
            indeed_bot_controller.unregister_polling_session(run_id)
        elif agent_run_template_name == "ziprecruiter-search":
            ziprecruiter_bot_controller.unregister_polling_session(run_id)
        elif agent_run_template_name == "glassdoor-search":
            glassdoor_bot_controller.unregister_polling_session(run_id)
        elif agent_run_template_name == "dice-search":
            dice_bot_controller.unregister_polling_session(run_id)
        elif agent_run_template_name == "autonomous-auto-search":
            autonomous_search_controller.unregister_polling_session(run_id)
        logger.info(f"Unregistered {agent_run_template_name} from polling: {run_id}")

    # ------------------------------------------------------------------
    def _launch_bot(
        self,
        agent_run_template_name: str,
        run_id: str,
        plan: AgentRunPlan,
    ) -> tuple[bool, str]:
        user_id = self._active_user_id or "infinite_hunt_user"

        try:
            if agent_run_template_name in LINKEDIN_WORKFLOWS:
                # Get linkedin_starter_url from platform config if available
                linkedin_starter_url = getattr(
                    plan.platform_config, "linkedin_starter_url", None
                )
                # Use controller to properly register and manage the bot.
                # For LinkedIn, the controller expects a session_id and an optional bot_config
                # containing workflowRunId and linkedinStarterUrl.
                bot_config: dict[str, Any] = {"workflowRunId": run_id}
                if linkedin_starter_url:
                    bot_config["linkedinStarterUrl"] = linkedin_starter_url

                result = linkedin_bot_controller.start_hunting_controller(
                    user_id=user_id,
                    workflow_run_id=run_id,
                    bot_config=bot_config,
                )
                return result.get("success", False), result.get(
                    "message", "Unknown LinkedIn error"
                )

            if agent_run_template_name == "indeed-search":
                # Use controller to properly register and manage the bot
                result = indeed_bot_controller.start_searching_controller(
                    user_id=user_id,
                    workflow_run_id=run_id,
                )
                return result.get("success", False), result.get(
                    "message", "Unknown Indeed error"
                )

            if agent_run_template_name == "ziprecruiter-search":
                # Use controller to properly register and manage the bot
                result = ziprecruiter_bot_controller.start_searching_controller(
                    user_id=user_id,
                    workflow_run_id=run_id,
                )
                return result.get("success", False), result.get(
                    "message", "Unknown ZipRecruiter error"
                )

            if agent_run_template_name == "glassdoor-search":
                # Use controller to properly register and manage the bot
                result = glassdoor_bot_controller.start_searching_controller(
                    user_id=user_id,
                    workflow_run_id=run_id,
                )
                return result.get("success", False), result.get(
                    "message", "Unknown Glassdoor error"
                )

            if agent_run_template_name == "dice-search":
                # Use controller to properly register and manage the bot
                result = dice_bot_controller.start_searching_controller(
                    user_id=user_id,
                    workflow_run_id=run_id,
                )
                return result.get("success", False), result.get(
                    "message", "Unknown Dice error"
                )

            if agent_run_template_name == "autonomous-auto-search":
                return self._run_autonomous_bot(user_id, run_id, plan)

            return False, f"No bot registered for {agent_run_template_name}"
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception(
                "Bot launcher crashed for %s: %s", agent_run_template_name, exc
            )
            return False, str(exc)

    def _run_autonomous_bot(
        self, user_id: str, run_id: str, plan: AgentRunPlan
    ) -> tuple[bool, str]:
        config: AutonomousBotConfig = plan.platform_config
        credentials = self._wait_for_llm_credentials(run_id, config.llm_provider)
        if not credentials:
            msg = "Missing LLM credentials for the autonomous agent."
            return False, msg

        # Create callback to store activity messages
        def activity_callback(message: dict[str, Any]) -> None:
            # Store directly to autonomous_search_controller activity_messages
            with autonomous_search_controller._message_lock:
                if run_id not in autonomous_search_controller.activity_messages:
                    autonomous_search_controller.activity_messages[run_id] = []
                autonomous_search_controller.activity_messages[run_id].append(message)
                # Limit queue size
                if len(autonomous_search_controller.activity_messages[run_id]) > 10000:
                    autonomous_search_controller.activity_messages[
                        run_id
                    ] = autonomous_search_controller.activity_messages[run_id][-10000:]

        bot = AutonomousSearchBot(
            user_id=user_id,
            session_id=config.session_id,
            workflow_run_id=run_id,
            websocket_callback=activity_callback,
            custom_criteria=config.custom_criteria,
            start_url=config.starting_url,
            agent_instructions=config.agent_instructions,
            max_jobs=config.max_jobs_per_platform,
            blacklist_companies=config.blacklist_companies,
            skip_staffing_companies=config.skip_staffing_companies,
            resume_id=config.resume_id,
            generate_ats_resume=config.generate_ats_resume,
            ats_template_id=config.selected_ats_template_id,
            llm_provider=config.llm_provider,
            llm_api_key=credentials.get("api_key"),
            llm_model=credentials.get("model") or config.llm_model,
            llm_endpoint=credentials.get("endpoint") or config.llm_endpoint,
            max_running_time=config.max_running_time,
            use_vision=config.use_vision,
        )

        validation = bot.start_searching()
        if not validation.get("success"):
            msg = validation.get("message", "Autonomous bot failed validation")
            return False, msg

        from autonomous_search_bot.actions import StartSearchingAction

        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            action = StartSearchingAction(bot)
            loop.run_until_complete(action.execute())
            return True, "Completed autonomous search"
        except Exception as exc:  # pragma: no cover - surfaced to UI
            logger.exception("Autonomous bot crashed: %s", exc)
            return False, str(exc)
        finally:
            try:
                loop.close()
                asyncio.set_event_loop(None)
            except Exception:
                pass

    def _wait_for_llm_credentials(
        self, run_id: str, provider: Optional[str], timeout: float = 120.0
    ) -> dict[str, str] | None:
        if not provider:
            return None

        start = time.monotonic()
        while time.monotonic() - start < timeout and not self._stop_event.is_set():
            creds = LLMCredentialManager.load_credentials(run_id, provider)
            if creds and creds.get("api_key"):
                return creds
            self._interruptible_sleep(2.0)
        return None


# Global helper used by FastAPI server startup
infinite_hunt_manager: Optional[InfiniteHuntManager] = None


def initialize_infinite_hunt_manager() -> InfiniteHuntManager:
    global infinite_hunt_manager
    if infinite_hunt_manager is None:
        infinite_hunt_manager = InfiniteHuntManager(supabase_client)
    return infinite_hunt_manager
