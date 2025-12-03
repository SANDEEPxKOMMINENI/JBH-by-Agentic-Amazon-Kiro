"""Pydantic model for the autonomous browser-use bot configuration."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, PositiveInt


class AutonomousPlatformSettings(BaseModel):
    """Per-job-board instructions consumed by the autonomous agent."""

    name: str = Field(..., description="Display name for the platform")
    search_url: Optional[str] = Field(
        default=None, description="Default URL to seed the browser-use agent"
    )
    instructions: Optional[str] = Field(
        default=None, description="Platform-specific scraping instructions"
    )
    allow_apply: bool = Field(
        True, description="Whether the agent should attempt applications"
    )
    max_jobs: Optional[PositiveInt] = Field(
        default=None, description="Optional override for jobs saved per platform"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Arbitrary platform metadata"
    )


class AutonomousBotConfig(BaseModel):
    workflow_run_id: str = Field(..., description="Workflow run identifier for polling")
    custom_criteria: str = Field(
        ..., description="High-level instructions for the autonomous agent"
    )
    starting_url: str = Field(..., description="Seed job board URL")
    agent_instructions: Optional[str] = Field(
        default=None, description="Additional agent prompt injected per step"
    )
    max_jobs_per_platform: PositiveInt = Field(
        10, description="Jobs to save per platform during a batch"
    )
    blacklist_companies: List[str] = Field(default_factory=list)
    skip_staffing_companies: bool = Field(
        True, description="Leverage staffing-company heuristics"
    )
    generate_ats_resume: bool = Field(
        False, description="Generate ATS resumes for queued jobs"
    )
    selected_ats_template_id: Optional[str] = Field(
        default=None, description="ATS template ID used for generation"
    )
    resume_id: Optional[str] = Field(
        default=None, description="Resume UUID to send when ATS generation disabled"
    )
    llm_provider: str = Field(..., description="Provider name (openai, azure, claude)")
    llm_model: str = Field(..., description="LLM model identifier")
    llm_endpoint: Optional[str] = Field(
        default=None,
        description="Azure OpenAI endpoint (required when llm_provider == 'azure')",
    )
    llm_api_key: Optional[str] = Field(
        default=None,
        description="Optional transient API key. WARNING: should be stored locally.",
    )
    use_vision: bool = Field(True, description="Enable vision-capable models")
    max_running_time: Optional[PositiveInt] = Field(
        default=None, description="Optional cap in minutes for the agent session"
    )
    platforms: List[AutonomousPlatformSettings] = Field(
        default_factory=list,
        description="Per-platform instructions and overrides for the autonomous agent",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Arbitrary runtime metadata (Langfuse, etc.)"
    )
