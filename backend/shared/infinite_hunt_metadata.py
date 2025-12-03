"""
In-memory metadata service for tracking infinite hunt and agent run state.

This is the first-hand source of truth for run status, avoiding database delays.
The metadata is maintained in-memory and updated directly by the infinite hunt
manager and bot controllers.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class JobStats:
    """Statistics for jobs processed in the current agent run."""

    queued: int = 0
    skipped: int = 0
    submitted: int = 0
    failed: int = 0

    def to_dict(self) -> Dict[str, int]:
        return {
            "queued": self.queued,
            "skipped": self.skipped,
            "submitted": self.submitted,
            "failed": self.failed,
        }

    def reset(self) -> None:
        self.queued = 0
        self.skipped = 0
        self.submitted = 0
        self.failed = 0


@dataclass
class AgentRunMetadata:
    """Metadata for a single agent run."""

    workflow_run_id: str
    workflow_id: str  # e.g., "linkedin-apply", "indeed-search"
    platform: str
    started_at: datetime
    job_stats: JobStats = field(default_factory=JobStats)
    status: str = "running"  # running, paused, completed, failed, stopped

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workflow_run_id": self.workflow_run_id,
            "workflow_id": self.workflow_id,
            "platform": self.platform,
            "started_at": self.started_at.isoformat(),
            "status": self.status,
            "job_stats": self.job_stats.to_dict(),
        }


@dataclass
class InfiniteHuntMetadata:
    """Metadata for the infinite hunt session."""

    is_running: bool = False
    session_id: Optional[str] = None
    started_at: Optional[datetime] = None
    agent_runs_created: int = 0
    agent_runs_by_template: Dict[str, int] = field(default_factory=dict)
    current_agent_run: Optional[AgentRunMetadata] = None
    cumulative_job_stats: JobStats = field(default_factory=JobStats)
    last_activity_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_running": self.is_running,
            "session_id": self.session_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "agent_runs_created": self.agent_runs_created,
            "agent_runs_by_template": self.agent_runs_by_template.copy(),
            "current_agent_run": (
                self.current_agent_run.to_dict() if self.current_agent_run else None
            ),
            "cumulative_job_stats": self.cumulative_job_stats.to_dict(),
            "last_activity_at": (
                self.last_activity_at.isoformat() if self.last_activity_at else None
            ),
        }


class InfiniteHuntMetadataService:
    """
    Singleton service for tracking infinite hunt and agent run metadata in-memory.

    This service is the first-hand source of truth for:
    - Whether infinite hunt is turned on
    - Job stats (queued/skipped/submitted) for the current agent run
    - Current active agent run info
    - Total agent runs created in the infinite hunt session
    """

    _instance: Optional["InfiniteHuntMetadataService"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "InfiniteHuntMetadataService":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._metadata = InfiniteHuntMetadata()
        self._data_lock = threading.RLock()
        logger.info("InfiniteHuntMetadataService initialized")

    # ------------------------------------------------------------------
    # Infinite Hunt State Management
    # ------------------------------------------------------------------

    def start_infinite_hunt(self, session_id: str) -> None:
        """Mark infinite hunt as started with a new session."""
        with self._data_lock:
            self._metadata.is_running = True
            self._metadata.session_id = session_id
            self._metadata.started_at = datetime.utcnow()
            self._metadata.agent_runs_created = 0
            self._metadata.agent_runs_by_template = {}
            self._metadata.current_agent_run = None
            self._metadata.cumulative_job_stats.reset()
            logger.info(f"Infinite hunt started with session_id: {session_id}")

    def stop_infinite_hunt(self) -> None:
        """Mark infinite hunt as stopped."""
        with self._data_lock:
            self._metadata.is_running = False
            self._metadata.last_activity_at = datetime.utcnow()
            if self._metadata.current_agent_run:
                self._metadata.current_agent_run.status = "stopped"
            logger.info(
                f"Infinite hunt stopped. Total agent runs: "
                f"{self._metadata.agent_runs_created}"
            )

    def pause_infinite_hunt(self) -> None:
        """Mark infinite hunt as paused."""
        with self._data_lock:
            if self._metadata.current_agent_run:
                self._metadata.current_agent_run.status = "paused"
            logger.info("Infinite hunt paused")

    def resume_infinite_hunt(self) -> None:
        """Mark infinite hunt as resumed."""
        with self._data_lock:
            if self._metadata.current_agent_run:
                self._metadata.current_agent_run.status = "running"
            logger.info("Infinite hunt resumed")

    def is_infinite_hunt_running(self) -> bool:
        """Check if infinite hunt is currently running."""
        with self._data_lock:
            return self._metadata.is_running

    def record_activity(self) -> None:
        """Record that activity has occurred."""
        with self._data_lock:
            self._metadata.last_activity_at = datetime.utcnow()
            logger.debug(f"Activity recorded at {self._metadata.last_activity_at}")

    def get_last_activity_at(self) -> Optional[datetime]:
        """Get the timestamp of the last recorded activity."""
        with self._data_lock:
            return self._metadata.last_activity_at

    # ------------------------------------------------------------------
    # Agent Run Management
    # ------------------------------------------------------------------

    def start_agent_run(
        self, workflow_run_id: str, workflow_id: str, platform: str
    ) -> None:
        """Start tracking a new agent run."""
        with self._data_lock:
            self._metadata.current_agent_run = AgentRunMetadata(
                workflow_run_id=workflow_run_id,
                workflow_id=workflow_id,
                platform=platform,
                started_at=datetime.utcnow(),
            )
            self._metadata.agent_runs_created += 1

            # Track runs by template type (workflow_id)
            if workflow_id not in self._metadata.agent_runs_by_template:
                self._metadata.agent_runs_by_template[workflow_id] = 0
            self._metadata.agent_runs_by_template[workflow_id] += 1

            logger.info(
                f"Agent run started: {workflow_run_id} ({workflow_id}). "
                f"Total runs: {self._metadata.agent_runs_created}, "
                f"Runs for {workflow_id}: "
                f"{self._metadata.agent_runs_by_template[workflow_id]}"
            )

    def complete_agent_run(self, workflow_run_id: str) -> None:
        """Mark the current agent run as completed."""
        with self._data_lock:
            if (
                self._metadata.current_agent_run
                and self._metadata.current_agent_run.workflow_run_id == workflow_run_id
            ):
                self._metadata.current_agent_run.status = "completed"
                # Add current run stats to cumulative stats
                current_stats = self._metadata.current_agent_run.job_stats
                self._metadata.cumulative_job_stats.queued += current_stats.queued
                self._metadata.cumulative_job_stats.skipped += current_stats.skipped
                self._metadata.cumulative_job_stats.submitted += current_stats.submitted
                self._metadata.cumulative_job_stats.failed += current_stats.failed
                logger.info(
                    f"Agent run completed: {workflow_run_id}. "
                    f"Stats: {current_stats.to_dict()}"
                )

    def fail_agent_run(self, workflow_run_id: str) -> None:
        """Mark the current agent run as failed."""
        with self._data_lock:
            if (
                self._metadata.current_agent_run
                and self._metadata.current_agent_run.workflow_run_id == workflow_run_id
            ):
                self._metadata.current_agent_run.status = "failed"
                logger.info(f"Agent run failed: {workflow_run_id}")

    def get_current_agent_run(self) -> Optional[Dict[str, Any]]:
        """Get current agent run metadata."""
        with self._data_lock:
            if self._metadata.current_agent_run:
                return self._metadata.current_agent_run.to_dict()
            return None

    def get_current_agent_run_id(self) -> Optional[str]:
        """Get current agent run ID."""
        with self._data_lock:
            if self._metadata.current_agent_run:
                return self._metadata.current_agent_run.workflow_run_id
            return None

    # ------------------------------------------------------------------
    # Job Stats Management
    # ------------------------------------------------------------------

    def increment_queued(self, workflow_run_id: Optional[str] = None) -> None:
        """Increment queued job count for current agent run."""
        with self._data_lock:
            if self._metadata.current_agent_run:
                if (
                    workflow_run_id is None
                    or self._metadata.current_agent_run.workflow_run_id
                    == workflow_run_id
                ):
                    self._metadata.current_agent_run.job_stats.queued += 1
                    logger.debug(
                        f"Incremented queued: {self._metadata.current_agent_run.job_stats.queued} "
                        f"for run {self._metadata.current_agent_run.workflow_run_id}"
                    )
                else:
                    logger.warning(
                        f"Failed to increment queued: workflow_run_id mismatch. "
                        f"Provided: {workflow_run_id}, "
                        f"Current: {self._metadata.current_agent_run.workflow_run_id}"
                    )
            else:
                logger.warning(
                    f"Failed to increment queued: no current agent run. "
                    f"Provided workflow_run_id: {workflow_run_id}"
                )

    def increment_skipped(self, workflow_run_id: Optional[str] = None) -> None:
        """Increment skipped job count for current agent run."""
        with self._data_lock:
            if self._metadata.current_agent_run:
                if (
                    workflow_run_id is None
                    or self._metadata.current_agent_run.workflow_run_id
                    == workflow_run_id
                ):
                    self._metadata.current_agent_run.job_stats.skipped += 1
                    logger.debug(
                        f"Incremented skipped: {self._metadata.current_agent_run.job_stats.skipped} "
                        f"for run {self._metadata.current_agent_run.workflow_run_id}"
                    )
                else:
                    logger.warning(
                        f"Failed to increment skipped: workflow_run_id mismatch. "
                        f"Provided: {workflow_run_id}, "
                        f"Current: {self._metadata.current_agent_run.workflow_run_id}"
                    )
            else:
                logger.warning(
                    f"Failed to increment skipped: no current agent run. "
                    f"Provided workflow_run_id: {workflow_run_id}"
                )

    def increment_submitted(self, workflow_run_id: Optional[str] = None) -> None:
        """Increment submitted job count for current agent run."""
        with self._data_lock:
            if self._metadata.current_agent_run:
                if (
                    workflow_run_id is None
                    or self._metadata.current_agent_run.workflow_run_id
                    == workflow_run_id
                ):
                    self._metadata.current_agent_run.job_stats.submitted += 1
                    logger.debug(
                        f"Incremented submitted: {self._metadata.current_agent_run.job_stats.submitted} "
                        f"for run {self._metadata.current_agent_run.workflow_run_id}"
                    )
                else:
                    logger.warning(
                        f"Failed to increment submitted: workflow_run_id mismatch. "
                        f"Provided: {workflow_run_id}, "
                        f"Current: {self._metadata.current_agent_run.workflow_run_id}"
                    )
            else:
                logger.warning(
                    f"Failed to increment submitted: no current agent run. "
                    f"Provided workflow_run_id: {workflow_run_id}"
                )

    def increment_failed(self, workflow_run_id: Optional[str] = None) -> None:
        """Increment failed job count for current agent run."""
        with self._data_lock:
            if self._metadata.current_agent_run:
                if (
                    workflow_run_id is None
                    or self._metadata.current_agent_run.workflow_run_id
                    == workflow_run_id
                ):
                    self._metadata.current_agent_run.job_stats.failed += 1
                    logger.debug(
                        f"Incremented failed: {self._metadata.current_agent_run.job_stats.failed} "
                        f"for run {self._metadata.current_agent_run.workflow_run_id}"
                    )
                else:
                    logger.warning(
                        f"Failed to increment failed: workflow_run_id mismatch. "
                        f"Provided: {workflow_run_id}, "
                        f"Current: {self._metadata.current_agent_run.workflow_run_id}"
                    )
            else:
                logger.warning(
                    f"Failed to increment failed: no current agent run. "
                    f"Provided workflow_run_id: {workflow_run_id}"
                )

    def get_current_job_stats(self) -> Dict[str, int]:
        """Get job stats for the current agent run."""
        with self._data_lock:
            if self._metadata.current_agent_run:
                return self._metadata.current_agent_run.job_stats.to_dict()
            return {"queued": 0, "skipped": 0, "submitted": 0, "failed": 0}

    def get_cumulative_job_stats(self) -> Dict[str, int]:
        """Get cumulative job stats for the entire infinite hunt session."""
        with self._data_lock:
            return self._metadata.cumulative_job_stats.to_dict()

    def get_agent_runs_by_template(self) -> Dict[str, int]:
        """Get count of agent runs created per template type."""
        with self._data_lock:
            return self._metadata.agent_runs_by_template.copy()

    # ------------------------------------------------------------------
    # Full Status
    # ------------------------------------------------------------------

    def get_full_status(self) -> Dict[str, Any]:
        """Get full infinite hunt status including all metadata."""
        with self._data_lock:
            return self._metadata.to_dict()

    def reset(self) -> None:
        """Reset all metadata (for testing or cleanup)."""
        with self._data_lock:
            self._metadata = InfiniteHuntMetadata()
            logger.info("InfiniteHuntMetadataService reset")


# Global singleton instance
_metadata_service: Optional[InfiniteHuntMetadataService] = None


def get_metadata_service() -> InfiniteHuntMetadataService:
    """Get the global metadata service instance."""
    global _metadata_service
    if _metadata_service is None:
        _metadata_service = InfiniteHuntMetadataService()
    return _metadata_service
