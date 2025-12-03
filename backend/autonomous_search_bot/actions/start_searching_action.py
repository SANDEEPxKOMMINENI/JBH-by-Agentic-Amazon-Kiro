"""Start Searching Action for Autonomous Search Bot."""

import asyncio
import logging
import os
import socket
from contextlib import closing, nullcontext
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import regex
from browser_use import ActionResult, Agent, Browser, Tools
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel, Field

from activity.base_activity import ActivityType
from autonomous_search_bot.actions.base_action import BaseAction
from autonomous_search_bot.util.cost_calculator import calculate_cost_from_tokens
from browser.browser_operator import BrowserOperator
from constants import SERVICE_GATEWAY_URL
from services.jwt_token_manager import jwt_token_manager
from shared.activity_manager import ActivityManager
from shared.ats_marker import ATSMarker
from shared.ats_marker.defs import ApplicantData
from shared.ats_marker.defs import JobData as ATSJobData
from shared.config_reader import ConfigReader
from shared.interest_marker import InterestMarker
from shared.interest_marker.defs import JobData as InterestJobData
from shared.models.application_history import ApplicationStatus
from shared.models.job_description import JobDescriptionModel
from util.application_history_id_generator import (
    generate_application_history_id,
    generate_job_description_id,
)

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_template_env = Environment(
    loader=FileSystemLoader(str(PROMPTS_DIR)),
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
)
_autonomous_prompt_template = _template_env.get_template("autonomous_search.jinja")
ATS_SKIP_THRESHOLD = 55


class JobRecord(JobDescriptionModel):
    """Flexible payload accepted from the agent before normalization."""

    id: Optional[str] = Field(
        default=None, description="Pre-generated job_description_id (if provided)"
    )
    application_url: Optional[str] = Field(
        default=None, description="Canonical application URL"
    )
    pos_context: Optional[str] = Field(
        default=None, description="Full job description text in markdown format"
    )
    platform: Optional[str] = Field(
        default=None, description="Site/platform identifier (e.g., Monster)"
    )
    notes: Optional[str] = Field(
        default=None, description="Additional context gathered while browsing"
    )
    source_url: Optional[str] = Field(
        default=None, description="Alternate URL if application_url is a redirect"
    )
    salary_range: Optional[list[int]] = Field(
        default=None,
        description="Lower and upper bounds of the salary range in the format with dollars: [lower, upper]",
    )
    location: Optional[str] = Field(
        default=None,
        description="Location of the job in the format of city, state, country",
    )


class JobEvaluationPayload(BaseModel):
    job_id: str = Field(..., description="Identifier returned by record_job_lead")


class StartSearchingAction(BaseAction):
    """Action to start the autonomous job searching process"""

    def __init__(self, bot_instance):
        super().__init__(bot_instance)
        self.config_reader = None
        self._recorded_jobs: Dict[str, JobDescriptionModel] = {}
        callback = getattr(self.bot, "activity_callback", None)
        bot_id = getattr(self.bot, "workflow_run_id", None)
        self.activity_manager: Optional[ActivityManager] = None
        self._last_agent_history_snapshot = ""
        self._last_usage_index = 0
        self._browser_operator: Optional[BrowserOperator] = None
        self._cdp_url: Optional[str] = None
        self._cdp_port: Optional[int] = None
        if callback:
            self.activity_manager = ActivityManager(
                websocket_callback=callback,
                bot_id=bot_id,
            )
            self.activity_manager.start_general_thread("Autonomous Search")
        if self.bot.workflow_run_id:
            try:
                reader = ConfigReader(self.bot.user_id, self.bot.workflow_run_id)
                if reader.load_configuration():
                    if self.bot.resume_id and (
                        reader.profile.resume_id != self.bot.resume_id
                    ):
                        reader._load_resume_config(self.bot.resume_id)
                    self.config_reader = reader
            except Exception:
                logger.warning(
                    "Failed to load ConfigReader for autonomous search",
                    exc_info=True,
                )

    @property
    def action_name(self) -> str:
        return "start_searching"

    async def execute(self):
        """Execute the autonomous searching process - async because browser_use requires it"""

        self.bot._loop = asyncio.get_running_loop()
        self.bot.status = "running"
        self._send_activity("action", "Starting autonomous Browser Use search agent...")

        if not self.bot.start_url:
            raise ValueError("Starting URL is required for autonomous search")

        # Initialize browser-use components
        self.bot.tools = self._register_tools()
        self.bot.llm = self._build_llm()
        cdp_url = await self._ensure_cdp_browser_if_needed()
        self.bot.browser = self._build_browser_session(cdp_url)

        task_prompt = self._build_task_prompt()

        self.bot.agent = Agent(
            task=task_prompt,
            llm=self.bot.llm,
            browser=self.bot.browser,
            tools=self.bot.tools,
            use_vision=getattr(self.bot, "use_vision", True),
            max_actions_per_step=10,
            max_failures=5,
            max_steps=80,
            calculate_cost=True,
        )

        history = None
        span_cm = (
            self.bot.langfuse.start_as_current_span(name="autonomous-auto-search")
            if self.bot.langfuse
            else nullcontext()
        )

        self._step_counter = 0

        try:
            with span_cm as span:
                if span is not None:
                    try:
                        span.update_trace(user_id=self.bot.user_id)
                        span.update(
                            metadata={"workflow_run_id": self.bot.workflow_run_id}
                        )
                    except Exception:
                        pass

                if self.bot.max_running_time and self.bot.max_running_time > 0:
                    timeout_seconds = self.bot.max_running_time * 60
                    try:
                        history = await asyncio.wait_for(
                            self.bot.agent.run(
                                on_step_start=self._on_step_start,
                                on_step_end=self._on_step_end,
                            ),
                            timeout=timeout_seconds,
                        )
                        self.bot.history = history
                    except asyncio.TimeoutError:
                        logger.warning(
                            f"Autonomous search timed out after {self.bot.max_running_time} minutes"
                        )
                        self._send_activity(
                            "result",
                            f"Search stopped: {self.bot.max_running_time} minute limit reached. "
                            f"Jobs saved: {self.bot.jobs_saved}. To remove this limit, provide your own API key.",
                            thread_status="queued" if self.bot.jobs_saved else "failed",
                        )
                        return
                else:
                    history = await self.bot.agent.run(
                        on_step_start=self._on_step_start,
                        on_step_end=self._on_step_end,
                    )
                    self.bot.history = history
        except Exception as exc:
            logger.exception("Autonomous search failed: %s", exc)
            self._send_activity(
                "result",
                f"Autonomous search failed: {exc}",
                thread_status="failed",
            )
            raise
        finally:
            await self._shutdown_agent()
            await self._graceful_browser_shutdown()
            await self._shutdown_browser_operator()
            self._flush_langfuse()
            self.bot.status = "stopped"

        if history is None:
            return

        self._log_cost_details(history)
        self._send_activity(
            "result",
            f"Autonomous search completed. Jobs saved: {self.bot.jobs_saved}",
            thread_status="queued" if self.bot.jobs_saved else None,
        )

    async def _graceful_browser_shutdown(self) -> None:
        if self.bot.browser:
            try:
                await self.bot.browser.stop()
            except Exception:
                logger.debug("Browser shutdown raised, ignoring", exc_info=True)
            finally:
                self.bot.browser = None

    async def _shutdown_agent(self) -> None:
        agent = getattr(self.bot, "agent", None)
        if not agent:
            return
        try:
            close_coro = getattr(agent, "close", None)
            if callable(close_coro):
                await close_coro()
        except Exception:
            logger.debug("Agent close raised, ignoring", exc_info=True)
        finally:
            self.bot.agent = None

    def _build_browser_session(self, cdp_url: Optional[str]) -> Browser:
        """Create a BrowserUse Browser configured for CDP when available."""
        browser_kwargs: Dict[str, Any] = {}
        if cdp_url:
            browser_kwargs["cdp_url"] = cdp_url
            logger.info("BrowserUse agent attaching to JobHuntr Chrome via %s", cdp_url)
        else:
            logger.info("BrowserUse agent will use bundled Chromium context")
        return Browser(**browser_kwargs)

    async def _ensure_cdp_browser_if_needed(self) -> Optional[str]:
        """Start (or re-use) the JobHuntr CDP Chrome session when enabled."""
        if not self._should_use_cdp_browser():
            return None

        if self._browser_operator and self._cdp_url:
            return self._cdp_url

        return await self._start_cdp_browser()

    def _should_use_cdp_browser(self) -> bool:
        """Determine whether the autonomous agent should attach via CDP."""
        override = os.getenv("JOBHUNTR_AUTONOMOUS_BROWSER_MODE")
        if override:
            return override.lower() not in {"bundled", "off", "disabled", "none"}

        requested = os.getenv("JOBHUNTR_BROWSER_MODE")
        if requested and requested.lower() == "bundled":
            return False

        return True

    def _resolve_cdp_port(self) -> int:
        """Select the CDP port (honor env override, otherwise pick a free port)."""
        env_port = os.getenv("JOBHUNTR_CDP_PORT")
        if env_port:
            try:
                port = int(env_port)
                if port > 0:
                    return port
            except ValueError:
                logger.warning(
                    "Invalid JOBHUNTR_CDP_PORT=%s; selecting a random port", env_port
                )

        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            sock.bind(("127.0.0.1", 0))
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            return sock.getsockname()[1]

    async def _start_cdp_browser(self) -> Optional[str]:
        """Launch BrowserOperator in CDP mode so BrowserUse can reuse the JobHuntr Chrome profile."""
        try:
            cdp_port = self._resolve_cdp_port()
            self._cdp_port = cdp_port
            os.environ["JOBHUNTR_BROWSER_MODE"] = "cdp"
            os.environ["JOBHUNTR_CDP_PORT"] = str(cdp_port)
            # Fetch headless_on setting from workflow run config
            headless_on = False
            try:
                from services.supabase_client import supabase_client

                workflow_run = supabase_client.get_workflow_run(
                    self.bot.workflow_run_id
                )
                if workflow_run:
                    headless_on = getattr(workflow_run, "headless_on", False) or False
                    logger.info(f"Using headless mode: {headless_on}")
            except Exception as e:
                logger.warning(f"Failed to fetch headless_on setting: {e}")

            operator = BrowserOperator(headless=headless_on)
            await asyncio.to_thread(operator.start)
            self._browser_operator = operator
            self._cdp_url = f"http://127.0.0.1:{cdp_port}"
            logger.info(
                "Started JobHuntr Chrome via CDP on port %s; BrowserUse will reuse the logged-in profile",
                cdp_port,
            )
            return self._cdp_url
        except Exception:
            logger.warning(
                "Failed to bootstrap Chrome via CDP; falling back to bundled browser_use Chromium",
                exc_info=True,
            )
            self._cdp_url = None
            self._cdp_port = None
            return None

    async def _shutdown_browser_operator(self) -> None:
        """Close the BrowserOperator instance if we launched one."""
        if not self._browser_operator:
            return

        operator = self._browser_operator
        self._cdp_url = None
        try:
            await asyncio.to_thread(operator.close)
        except Exception:
            logger.debug("BrowserOperator close raised, ignoring", exc_info=True)

    def _register_tools(self) -> Tools:
        """Register browser_use tools available to the agent"""
        tools = Tools()

        @tools.action(
            description="Record a promising job lead and immediately run interest + ATS analysis."
        )
        async def process_job_lead(job: JobRecord) -> ActionResult:
            job_record = (
                job if isinstance(job, JobRecord) else JobRecord.model_validate(job)
            )
            missing_fields = []
            if not (job_record.application_url or job_record.source_url):
                missing_fields.append("application_url")
            if not job_record.company_name:
                missing_fields.append("company_name")
            if not job_record.job_title:
                missing_fields.append("job_title")
            if not job_record.pos_context:
                missing_fields.append("pos_context")

            if missing_fields:
                guidance = "Please reopen the detail page and extract the full description before retrying."
                message = (
                    "process_job_lead needs more data: missing "
                    + ", ".join(missing_fields)
                    + f". {guidance}"
                )
                return ActionResult(
                    extracted_content=message,
                    error="missing_fields",
                )

            try:
                job_id, record_message = await self._record_job_lead(job_record)
            except Exception as exc:
                logger.exception("Failed to record job via tool: %s", exc)
                return ActionResult(
                    extracted_content=f"Failed to record job: {exc}",
                    error=str(exc),
                )
            if not job_id:
                return ActionResult(extracted_content=record_message)

            try:
                eval_message = await self._evaluate_job_lead(job_id)
                combined_message = f"{record_message}\n{eval_message}"
                return ActionResult(
                    extracted_content=combined_message,
                    metadata={"job_id": job_id},
                )
            except Exception as exc:
                logger.exception("Job evaluation tool failed: %s", exc)
                return ActionResult(
                    extracted_content=f"{record_message}\nJob evaluation failed: {exc}",
                    metadata={"job_id": job_id},
                    error=str(exc),
                )

        return tools

    async def _on_step_start(self, agent) -> None:
        """Lifecycle hook executed at the start of every step."""
        self._step_counter += 1
        url = None
        try:
            url = await agent.browser_session.get_current_page_url()
        except Exception:
            url = None
        message = f"Step {self._step_counter} starting"
        if url:
            message += f" at {url}"
        self._send_activity("action", message)

    async def _on_step_end(self, agent) -> None:
        """Lifecycle hook executed at the end of every step."""
        try:
            last_step = agent.history.history[-1]

            # Extract result content
            last_result = last_step.result[0].extracted_content
            last_result = self._extract_result_text(last_result)
            # remove emoji in last_result
            last_result = regex.sub(r"^\p{Emoji}+\s*", "", last_result)
            if last_result:
                self._send_activity(
                    "result",
                    last_result,
                )

            # Calculate cost for the last step
            step_cost_info = self._extract_step_cost(agent)
            if step_cost_info:
                step_cost = step_cost_info.get("cost_usd", 0.0)
                step_tokens = step_cost_info.get("total_tokens", 0)
                if step_cost > 0 or step_tokens > 0:
                    cost_message = (
                        f"Step {self._step_counter} cost: "
                        f"${step_cost:.4f} USD ({step_tokens:,} tokens)"
                    )
                    self._send_activity("action", cost_message)
                    logger.debug(
                        f"Step {self._step_counter} cost breakdown: "
                        f"input={step_cost_info.get('input_tokens', 0)}, "
                        f"output={step_cost_info.get('output_tokens', 0)}, "
                        f"cost=${step_cost:.4f}"
                    )

            # Extract and send next_goal and thinking from model_output
            if hasattr(last_step, "model_output") and last_step.model_output:
                model_output = last_step.model_output

                # Extract thinking
                thinking = getattr(model_output, "thinking", None)
                if thinking:
                    self._send_activity("thinking", thinking)

                # Extract next_goal
                next_goal = getattr(model_output, "next_goal", None)
                if next_goal:
                    self._send_activity("thinking", f"Next goal: {next_goal}")

        except Exception:
            logger.debug("Failed to diff agent history description", exc_info=True)

    def _build_llm(self):
        """Build and configure LLM client based on provider settings"""
        if (
            not self.bot.llm_provider
            or not self.bot.llm_api_key
            or not self.bot.llm_model
        ):
            raise RuntimeError(
                "LLM API configuration is required. Please provide your API key, provider, and model selection."
            )

        if self.bot.llm_provider == "azure" and not self.bot.llm_endpoint:
            raise RuntimeError(
                "Azure OpenAI requires an endpoint URL. Please provide your Azure OpenAI endpoint."
            )

        try:
            llm = None
            provider = (self.bot.llm_provider or "").lower()
            if provider == "openai":
                from browser_use.llm.openai.chat import ChatOpenAI

                # o1 models use max_completion_tokens instead of max_tokens
                model_name = self.bot.llm_model.lower()
                llm_kwargs = {
                    "model": self.bot.llm_model,
                    "api_key": self.bot.llm_api_key,
                }

                # o1 models don't support temperature and use max_completion_tokens
                if "o1" in model_name:
                    # o1 models use default settings (no temperature, no explicit max_tokens)
                    logger.info(
                        f"Using OpenAI {self.bot.llm_model} with default settings (no temperature, using max_completion_tokens)"
                    )
                else:
                    llm_kwargs["temperature"] = 0.7

                llm = ChatOpenAI(**llm_kwargs)
            elif provider == "azure":
                from browser_use.llm.azure.chat import ChatAzureOpenAI

                llm = ChatAzureOpenAI(
                    model=self.bot.llm_model,
                    api_key=self.bot.llm_api_key,
                    azure_endpoint=self.bot.llm_endpoint,
                    temperature=0.7,
                )
            elif provider == "claude":
                from browser_use.llm.anthropic.chat import ChatAnthropic

                llm = ChatAnthropic(
                    model=self.bot.llm_model,
                    api_key=self.bot.llm_api_key,
                    temperature=0.7,
                )
            elif provider == "gemini":
                from browser_use.llm.google.chat import ChatGoogle

                llm = ChatGoogle(
                    model=self.bot.llm_model,
                    api_key=self.bot.llm_api_key,
                    temperature=0.7,
                )
            elif provider == "browseruse" or provider == "browser_use":
                from browser_use.llm.browser_use.chat import ChatBrowserUse

                llm = ChatBrowserUse(
                    api_key=self.bot.llm_api_key,
                    model=self.bot.llm_model or "chat-browser-use-latest",
                )
            else:
                raise RuntimeError(f"Unsupported LLM provider: {self.bot.llm_provider}")

            if llm is None:
                raise RuntimeError("Failed to initialize LLM client.")

            return llm

        except ImportError as e:
            raise RuntimeError(
                f"Failed to import LLM provider {self.bot.llm_provider}: {e}"
            )
        except Exception as exc:
            raise RuntimeError(f"Failed to configure LLM: {exc}") from exc

    def _build_task_prompt(self) -> str:
        """Build the task prompt for the agent based on user instructions and the starting URL"""
        general_criteria = self.bot.custom_criteria
        if not general_criteria:
            raise RuntimeError(
                "Custom search criteria are required for autonomous search"
            )
        agent_instructions = self.bot.agent_instructions or ""
        rendered_prompt = _autonomous_prompt_template.render(
            general_criteria=general_criteria,
            start_url=self.bot.start_url,
            agent_instructions=agent_instructions,
            max_jobs=self.bot.max_jobs_per_platform,
            blacklist_companies=self.bot.blacklist_companies,
            skip_staffing_companies=self.bot.skip_staffing_companies,
        )
        return rendered_prompt.strip()

    async def _record_job_lead(self, job: JobRecord) -> Tuple[str, str]:
        """Persist job details and return (job_id, message)."""
        if self.bot._stop_requested:
            raise RuntimeError("Stop requested – ignoring new jobs")

        job_record = (
            job if isinstance(job, JobRecord) else JobRecord.model_validate(job)
        )
        job_payload = job_record.model_dump()
        job_payload.pop("id", None)

        application_url = job_payload.get("application_url") or job_payload.get(
            "source_url"
        )
        if not application_url:
            raise ValueError("Job payload missing application_url")

        job_title = job_payload.get("job_title", "Unknown role")
        company = job_payload.get("company_name", "Unknown company")

        try:
            job_description_id = generate_job_description_id(application_url)
        except Exception:
            fallback_url = f"{application_url}#{job_title}-{company}"
            job_description_id = generate_job_description_id(fallback_url)

        normalized_payload = {
            "id": job_description_id,
            **job_payload,
            "application_url": application_url,
            "job_title": job_title,
            "company_name": company,
        }
        if not normalized_payload.get("pos_context"):
            normalized_payload.pop("pos_context", None)
        salary_value = normalized_payload.get("salary_range")
        if isinstance(salary_value, (list, tuple)):
            try:
                low, high = salary_value
                normalized_payload["salary_range"] = f"${low:,}–${high:,}"
            except Exception:
                normalized_payload["salary_range"] = None
        elif isinstance(salary_value, (int, float)):
            normalized_payload["salary_range"] = f"${salary_value:,}"
        normalized_record = JobDescriptionModel.model_validate(
            {
                "id": job_description_id,
                **normalized_payload,
            }
        )

        application_id = generate_application_history_id(
            application_url,
            self.bot.user_id,
            company_name=company,
            job_title=job_title,
        )
        self._recorded_jobs[application_id] = normalized_record
        self.bot.application_history_tracker.cur_recording_app_history_id = (
            application_id
        )

        tracker_updates = {
            "job_description_id": job_description_id,
            "application_url": application_url,
            "company_name": company,
            "location": job_record.location or "",
            "job_title": job_title,
            "pos_context": job_record.pos_context or "",
            "job_type": job_record.job_type or job_payload.get("platform") or "",
            "salary_range": job_record.salary_range
            or normalized_payload.get("salary_range"),
            "post_time": job_record.post_time or datetime.now().isoformat(),
            "num_applicants": job_payload.get("num_applicants", 0),
            "workflow_run_id": self.bot.workflow_run_id,
            "status": ApplicationStatus.STARTED.value,
            "notes": job_payload.get("notes", ""),
        }

        if self.config_reader and getattr(
            self.config_reader.profile, "resume_id", None
        ):
            tracker_updates["resume_id"] = self.config_reader.profile.resume_id

        if self.bot.generate_ats_resume and self.bot.ats_template_id:
            tracker_updates["ats_template_id"] = self.bot.ats_template_id

        for attr, value in tracker_updates.items():
            self.bot.application_history_tracker.update_application(
                application_id, attr, value
            )

        existing_job = self.bot.application_history_tracker.get_job_item_from_history(
            application_id
        )
        if existing_job:
            existing_status = existing_job.get("status")

            # Jobs in this set will be skipped
            duplicate_statuses = [
                ApplicationStatus.QUEUED.value,
                ApplicationStatus.SUBMITTING.value,
                ApplicationStatus.APPLIED.value,
                ApplicationStatus.REMOVED.value,
            ]

            # Add SKIPPED to skip list if skip_previously_skipped_jobs is enabled
            if self.bot.config_reader.filters.skip_previously_skipped_jobs:
                duplicate_statuses.append(ApplicationStatus.SKIPPED.value)

            duplicate_statuses = set(duplicate_statuses)

            if existing_status in duplicate_statuses:
                thread_title = f"{company} - {job_title}"
                message = f"Skipping {company} | {job_title} (already processed with status: {existing_status})"
                self._send_activity(
                    "result",
                    message,
                    thread_title=thread_title,
                    thread_status=existing_status,
                )
                self.bot.application_history_tracker.reset_application_history()
                return None, message

        self.bot.application_history_tracker.create_application_history()

        thread_title = f"{company} - {job_title}"
        if self.activity_manager:
            self.activity_manager.start_application_thread(
                company, job_title, ApplicationStatus.STARTED.value
            )

        message = f"Recorded {company} | {job_title}. job_id={application_id}."
        self._send_activity(
            "action",
            message,
            thread_title=thread_title,
            thread_status=ApplicationStatus.STARTED.value,
        )
        return application_id, message

    async def _evaluate_job_lead(self, job_id: str) -> str:
        if not job_id:
            raise ValueError("job_id is required for job evaluation")

        job_record = self._recorded_jobs.get(job_id)
        if not job_record:
            stored = self.bot.application_history_tracker.get_job_item_from_history(
                job_id
            )
            if not stored:
                raise ValueError(f"No recorded job found for id {job_id}")
            job_record = JobDescriptionModel.model_validate(stored)
            self._recorded_jobs[job_id] = job_record

        self.bot.application_history_tracker.cur_recording_app_history_id = job_id
        job_data = job_record.model_dump()
        job_title = job_record.job_title or "Unknown role"
        company = job_record.company_name or "Unknown company"
        thread_title = f"{company} - {job_title}"
        self._send_activity(
            "action",
            f"Evaluating {company} | {job_title}",
            thread_title=thread_title,
            thread_status="Started",
        )

        skip_reasons: list[str] = []
        if self._is_blacklisted_company(company):
            skip_reasons.append("Company is on your blacklist")
        if self.bot.skip_staffing_companies and self._looks_like_staffing_company(
            company
        ):
            skip_reasons.append("Detected staffing/recruiting organization")

        # Interest marker
        interest_result = self._run_interest_marker(job_record)
        if interest_result:
            formatted = interest_result.get("formatted")
            if formatted:
                self._send_activity("thinking", formatted, thread_title=thread_title)
            if interest_result.get("should_skip"):
                skip_reasons.append(
                    interest_result.get("reasoning")
                    or "Interest marker recommended skipping this role"
                )

        # ATS analysis
        if not skip_reasons:
            if self.config_reader and self.config_reader.profile.resume:
                try:
                    analysis = await self._evaluate_job_fit(
                        job_record, application_id=job_id, persist=True
                    )
                    summary = analysis.get("formatted")
                    if summary:
                        self._send_activity(
                            "thinking", summary, thread_title=thread_title
                        )
                    score = analysis.get("score")
                    if isinstance(score, (int, float)) and score < ATS_SKIP_THRESHOLD:
                        skip_reasons.append(
                            f"ATS score {int(score)}/100 below threshold {ATS_SKIP_THRESHOLD}"
                        )
                except Exception as exc:
                    skip_reasons.append(f"ATS analysis failed: {exc}")
                    logger.warning("ATS analysis failed: %s", exc, exc_info=True)
            else:
                self._send_activity(
                    "action",
                    "Resume not configured – skipping ATS analysis.",
                    thread_title=thread_title,
                )

        final_status = (
            ApplicationStatus.SKIPPED.value
            if skip_reasons
            else ApplicationStatus.QUEUED.value
        )
        if self.activity_manager:
            self.activity_manager.update_application_status(final_status)
        self.bot.application_history_tracker.update_application(
            job_id, "status", final_status
        )
        self.bot.application_history_tracker.sync_application_history()
        self.bot.application_history_tracker.reset_application_history()
        self._recorded_jobs.pop(job_id, None)

        if final_status == ApplicationStatus.QUEUED.value:
            self.bot.jobs_saved += 1
            message = f"Queued: {company} | {job_title}"
            self._send_activity(
                "result",
                message,
                thread_title=thread_title,
                thread_status=ApplicationStatus.QUEUED.value,
            )
        else:
            reason_text = "; ".join(skip_reasons) if skip_reasons else "Not a fit"
            message = f"Skipped: {company} | {job_title} – {reason_text}"
            self._send_activity(
                "result",
                message,
                thread_title=thread_title,
                thread_status=ApplicationStatus.SKIPPED.value,
            )
        if self.activity_manager:
            self.activity_manager.start_general_thread("Autonomous Search")
        return message

    def _log_cost_details(self, history) -> None:
        """Log cost and usage details from browser_use history"""
        try:
            cost_info = self._extract_cost_info(history)
        except Exception:
            logger.debug("Unable to extract cost information", exc_info=True)
            return

        if not cost_info:
            return

        message = (
            f"Usage summary – steps: {cost_info['total_steps']}, "
            f"tokens: {cost_info['total_tokens']:,}, "
            f"estimated cost: ${cost_info['estimated_cost_usd']:.4f}"
        )
        self._send_activity("action", message)

        if self.bot.langfuse:
            try:
                with self.bot.langfuse.start_as_current_generation(
                    name="autonomous-cost-summary",
                    model=getattr(self.bot.llm, "model", "browser-use"),
                ) as generation:
                    generation.update(
                        output=message,
                        usage={
                            "input": cost_info["input_tokens"],
                            "output": cost_info["output_tokens"],
                            "total": cost_info["total_tokens"],
                            "unit": "TOKENS",
                        },
                    )
            except Exception:
                logger.debug("Failed to publish Langfuse summary", exc_info=True)

    def _extract_step_cost(self, agent) -> Optional[Dict[str, Any]]:
        """Extract cost and token usage for the last step from agent history"""
        try:
            token_cost_service = getattr(agent, "token_cost_service", None)
            if not token_cost_service:
                return None

            # Get model name and provider for pricing lookup
            provider = getattr(self.bot, "llm_provider", None) or "openai"
            model_name = (
                getattr(self.bot, "llm_model", None)
                or getattr(self.bot.llm, "model", None)
                if hasattr(self.bot, "llm")
                else "gpt-4"
            ) or "gpt-4"

            usage_history = getattr(token_cost_service, "usage_history", None)
            if not usage_history:
                return None
            new_entries = usage_history[self._last_usage_index :]
            if not new_entries:
                return None
            self._last_usage_index = len(usage_history)

            input_tokens = 0
            output_tokens = 0
            step_cost = 0.0
            for entry in new_entries:
                usage = entry.usage
                entry_prompt = getattr(usage, "prompt_tokens", 0) or 0
                entry_completion = getattr(usage, "completion_tokens", 0) or 0
                input_tokens += entry_prompt
                output_tokens += entry_completion
                entry_model = getattr(entry, "model", None) or model_name
                step_cost += calculate_cost_from_tokens(
                    entry_prompt,
                    entry_completion,
                    provider,
                    entry_model,
                )

            total_tokens = input_tokens + output_tokens
            if total_tokens == 0:
                return None

            return {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "cost_usd": step_cost,
            }

        except Exception as e:
            logger.debug(f"Failed to extract step cost: {e}", exc_info=True)
            return None

    def _extract_result_text(self, text: Optional[str]) -> str:
        """Return inner <result> content when present, otherwise the original text."""
        if not text:
            return ""
        match = regex.search(
            r"<result>(.*?)</result>", text, regex.DOTALL | regex.IGNORECASE
        )
        if match:
            return match.group(1).strip()
        return text

    def _extract_cost_info(self, history) -> Dict[str, Any]:
        """Extract cost and usage information from browser_use history"""
        total_steps = history.number_of_steps()
        input_tokens = 0
        output_tokens = 0
        total_cost = 0.0

        usage = getattr(history, "usage", None)
        if usage:
            input_tokens = getattr(usage, "total_prompt_tokens", 0) or usage.get(
                "prompt_tokens", 0
            )
            output_tokens = getattr(usage, "total_completion_tokens", 0) or usage.get(
                "completion_tokens", 0
            )
            total_cost = getattr(usage, "total_cost", 0.0) or usage.get(
                "total_cost", 0.0
            )

        total_tokens = input_tokens + output_tokens
        if total_tokens == 0 and total_steps:
            total_tokens = total_steps * 2000
            input_tokens = int(total_tokens * 0.7)
            output_tokens = total_tokens - input_tokens

        if total_cost == 0.0 and total_tokens:
            # Get model name and provider for pricing lookup
            provider = getattr(self.bot, "llm_provider", None) or "openai"
            model_name = (
                getattr(self.bot, "llm_model", None)
                or getattr(self.bot.llm, "model", None)
                if hasattr(self.bot, "llm")
                else "gpt-4"
            ) or "gpt-4"

            total_cost = calculate_cost_from_tokens(
                input_tokens, output_tokens, provider, model_name
            )

        return {
            "total_steps": total_steps,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "estimated_cost_usd": total_cost,
        }

    async def _evaluate_job_fit(
        self,
        job: JobRecord,
        application_id: Optional[str] = None,
        persist: bool = True,
    ) -> Dict[str, Any]:
        if not self.config_reader or not self.config_reader.profile.resume:
            raise RuntimeError(
                "Resume data not available. Please select a resume before running ATS analysis."
            )
        loop = asyncio.get_running_loop()
        analysis = await loop.run_in_executor(None, self._run_ats_analysis_sync, job)
        if persist and application_id and analysis:
            self._persist_ats_results(application_id, analysis)
        return analysis

    def _run_ats_analysis_sync(self, job: JobRecord) -> Dict[str, Any]:
        applicant_data = ApplicantData(
            resume=self.config_reader.profile.resume,
            additional_skills_and_experience=(
                getattr(self.config_reader.profile, "additional_experience", "") or ""
            ),
            selected_ats_template_id=getattr(
                self.config_reader.profile, "selected_ats_template_id", None
            ),
        )
        job_payload = ATSJobData(
            job_title=job.job_title,
            job_description=job.pos_context,
            company_name=job.company_name,
            post_time=job.post_time or datetime.now().isoformat(),
            location=job.location or "",
        )
        user_token = jwt_token_manager.get_token()
        ats_marker = ATSMarker(
            job_data=job_payload,
            applicant_data=applicant_data,
            bot=self,
            display_thinking_callback=self._maybe_display_activity,
            service_gateway_url=SERVICE_GATEWAY_URL,
            user_token=user_token,
        )
        score, alignments, keywords = ats_marker.run()
        formatted = ats_marker.format_alignments(score, alignments)
        return {
            "score": score,
            "alignments": alignments,
            "keywords": keywords,
            "formatted": formatted,
        }

    def _persist_ats_results(
        self, application_id: str, analysis: Dict[str, Any]
    ) -> None:
        tracker = self.bot.application_history_tracker
        score = analysis.get("score")
        alignments = analysis.get("alignments") or []
        keywords = analysis.get("keywords") or []

        if isinstance(score, (int, float)):
            tracker.update_application(application_id, "ats_score", score)
        if alignments:
            tracker.update_application(
                application_id,
                "ats_alignments",
                self._alignments_to_dicts(alignments),
            )
        if keywords:
            tracker.update_application(
                application_id, "ats_keyword_to_add_to_resume", keywords
            )

    def _alignments_to_dicts(self, alignments) -> list:
        result = []
        for alignment in alignments:
            if hasattr(alignment, "to_dict"):
                result.append(alignment.to_dict())
            elif isinstance(alignment, dict):
                result.append(alignment)
        return result

    def _maybe_display_activity(self, text: str) -> None:
        if text:
            self._send_activity("thinking", text)

    def _run_interest_marker(self, job: JobRecord) -> Optional[Dict[str, Any]]:
        criteria = self.bot.custom_criteria
        if self.config_reader and getattr(
            self.config_reader.filters, "semantic_instructions", None
        ):
            fallback = self.config_reader.filters.semantic_instructions.strip()
            if fallback:
                criteria = fallback
        if not criteria:
            return None
        interest_job = InterestJobData(
            job_title=job.job_title,
            job_description=job.pos_context,
            company_name=job.company_name,
            post_time=job.post_time or datetime.now().isoformat(),
            location=job.location or "",
        )
        marker = InterestMarker(
            job_data=interest_job,
            original_job_search_criteria=criteria,
            display_thinking_callback=self._maybe_display_activity,
        )
        try:
            alignments, should_skip, reasoning = marker.run()
            formatted = marker.format_alignments(alignments)
            return {
                "alignments": alignments,
                "formatted": formatted,
                "should_skip": should_skip,
                "reasoning": reasoning,
            }
        except Exception as exc:
            logger.warning("Interest marker failed: %s", exc, exc_info=True)
            self._send_activity("action", f"Interest marker failed: {exc}")
            return None

    def _normalize_job_payload(self, job: Any) -> Dict[str, Any]:
        if isinstance(job, JobDescriptionModel):
            return job.model_dump()
        if isinstance(job, BaseModel):
            return job.model_dump()
        if isinstance(job, dict):
            return job
        raise ValueError("Unsupported job payload format")

    def _flush_langfuse(self) -> None:
        """Flush Langfuse client to ensure all traces are sent"""
        if self.bot.langfuse:
            try:
                self.bot.langfuse.flush()
            except Exception:
                logger.debug("Langfuse flush failed", exc_info=True)

    def _send_activity(
        self,
        message_type: str,
        message: str,
        thread_title: Optional[str] = None,
        thread_status: Optional[str] = None,
    ) -> None:
        """Send activity update via callback if available"""
        activity_type_map = {
            "action": ActivityType.ACTION,
            "result": ActivityType.RESULT,
            "thinking": ActivityType.THINKING,
        }
        activity_type = activity_type_map.get(message_type, ActivityType.ACTION)

        if self.activity_manager:
            if thread_status:
                self.activity_manager.current_thread_status = thread_status
            self.activity_manager.send_activity_message(
                message,
                activity_type=activity_type,
                thread_title=thread_title,
            )
            return
        if not self.bot.activity_callback:
            return
        payload = {
            "type": message_type,
            "message": message,
            "thread_title": thread_title,
            "thread_status": thread_status,
        }
        try:
            self.bot.activity_callback(payload)
        except Exception:
            logger.debug("Activity callback raised", exc_info=True)

    def _is_blacklisted_company(self, company_name: str) -> bool:
        if not company_name:
            return False
        lookup = getattr(self.bot, "blacklist_company_lookup", None)
        if not lookup:
            return False
        company_lower = company_name.lower()
        for blocked in lookup:
            if blocked and blocked in company_lower:
                return True
        return False

    def _looks_like_staffing_company(self, company_name: str) -> bool:
        if not company_name:
            return False
        company_lower = company_name.lower()
        staffing_keywords = (
            "staffing",
            "recruiting",
            "recruiter",
            "placement",
            "headhunter",
            "talent solutions",
            "talent agency",
            "employment agency",
            "search partners",
        )
        return any(keyword in company_lower for keyword in staffing_keywords)
