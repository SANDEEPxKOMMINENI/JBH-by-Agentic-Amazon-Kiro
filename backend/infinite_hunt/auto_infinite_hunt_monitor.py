"""
Auto Infinite Hunt Monitor - Periodically check and auto-start infinite hunt.

This monitor runs as a background thread that triggers every 30 minutes to:
1. Send a Mixpanel ping to indicate the monitor is alive
2. Check if auto_infinite_hunt_on is enabled in the database
3. Check if infinite hunt is currently NOT running
4. Validate the configuration (templates selected, instructions provided)

If all conditions are met, it automatically starts the infinite hunt.
"""

from __future__ import annotations

import logging
import platform
import subprocess
import threading
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional

import requests

if TYPE_CHECKING:
    from infinite_hunt.manager import InfiniteHuntManager

from constants import SERVICE_GATEWAY_URL
from services.jwt_token_manager import jwt_token_manager
from services.supabase_client import SupabaseClient
from shared.infinite_hunt_metadata import get_metadata_service

logger = logging.getLogger(__name__)

# Constants
DEFAULT_CHECK_INTERVAL_SECONDS = 30 * 60  # Default: 30 minutes
CONFIG_KEY_INTERVAL = "auto_infinite_hunt_idle_interval_s"


class AutoInfiniteHuntMonitor:
    """
    Background monitor for auto-start infinite hunt functionality.

    When enabled, this monitor triggers every 30 minutes to:
    1. Send a Mixpanel ping to indicate the monitor is alive
    2. Check if infinite hunt should be auto-started
    3. Validate configuration and start if conditions are met
    """

    def __init__(
        self,
        supabase: SupabaseClient,
        infinite_hunt_manager: "InfiniteHuntManager",
    ):
        self.supabase = supabase
        self.infinite_hunt_manager = infinite_hunt_manager

        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._is_enabled: bool = False

        # Track when we last auto-started to prevent rapid restarts
        # Initialize to current time to prevent immediate auto-start on first run
        self._last_auto_start_at: datetime = datetime.utcnow()
        self._last_check_at: datetime = datetime.utcnow()
        self._min_restart_interval_minutes = 5  # Don't auto-restart within 5 minutes

    def _get_check_interval(self) -> int:
        """Fetch check interval from dynamic_config table, fallback to default."""
        try:
            result = self.supabase.get_dynamic_config(CONFIG_KEY_INTERVAL)
            if result is not None:
                return int(result)
        except Exception as exc:
            logger.warning(
                f"Failed to fetch {CONFIG_KEY_INTERVAL} from dynamic_config: {exc}"
            )
        return DEFAULT_CHECK_INTERVAL_SECONDS

    def start(self) -> None:
        """Start the auto infinite hunt monitor background thread."""
        if self._monitor_thread and self._monitor_thread.is_alive():
            logger.debug("AutoInfiniteHuntMonitor already running")
            return

        logger.info("Starting AutoInfiniteHuntMonitor background thread")
        self._stop_event.clear()
        self._monitor_thread = threading.Thread(
            target=self._run_loop,
            name="AutoInfiniteHuntMonitor",
            daemon=True,
        )
        self._monitor_thread.start()

    def stop(self) -> None:
        """Stop the auto infinite hunt monitor background thread."""
        logger.info("Stopping AutoInfiniteHuntMonitor background thread")
        self._stop_event.set()
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5)

    def get_status(self) -> dict:
        """Get current auto infinite hunt monitor status for API response."""
        check_interval = self._get_check_interval()
        now = datetime.utcnow()

        # Calculate seconds until next check
        elapsed = (now - self._last_check_at).total_seconds()
        seconds_until_next_check = max(0, check_interval - int(elapsed))

        # Calculate next check timestamp
        next_check_at = self._last_check_at + timedelta(seconds=check_interval)

        return {
            "enabled": self._is_enabled,
            "check_interval_seconds": check_interval,
            "check_interval_minutes": check_interval / 60,
            "last_auto_start_at": self._last_auto_start_at.isoformat(),
            "last_check_at": self._last_check_at.isoformat(),
            "next_check_at": next_check_at.isoformat(),
            "seconds_until_next_check": seconds_until_next_check,
        }

    def _run_loop(self) -> None:
        """Main background loop that triggers based on dynamic_config interval."""
        logger.info("Auto infinite hunt monitor loop started")

        while not self._stop_event.is_set():
            # Record check time for countdown calculation
            self._last_check_at = datetime.utcnow()

            # Fetch interval from database each cycle (allows dynamic updates)
            check_interval = self._get_check_interval()
            logger.debug(
                f"Auto infinite hunt monitor check (interval: {check_interval}s)"
            )

            try:
                # Send Mixpanel ping to indicate monitor is alive
                self._send_monitor_alive_ping()

                # Check and maybe auto-start infinite hunt
                self._check_and_maybe_auto_start()

            except Exception as exc:
                logger.exception(f"Auto infinite hunt monitor error: {exc}")

            # Sleep for the configured interval (interruptible)
            self._interruptible_sleep(check_interval)

        logger.info("Auto infinite hunt monitor loop exited")

    def _interruptible_sleep(self, duration: float) -> None:
        """Sleep that can be interrupted by stop event."""
        end_time = time.time() + duration
        while time.time() < end_time:
            if self._stop_event.is_set():
                return
            time.sleep(min(1.0, end_time - time.time()))

    def _send_monitor_alive_ping(self) -> None:
        """Send a Mixpanel ping event to indicate the monitor is alive."""
        try:
            token = jwt_token_manager.get_token()
            if not token:
                logger.debug("No JWT token available for Mixpanel ping, skipping")
                return

            url = f"{SERVICE_GATEWAY_URL.rstrip('/')}/api/analytics/mixpanel"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            payload = {
                "event_name": "auto_infinite_hunt_monitor_alive",
                "properties": {
                    "auto_infinite_hunt_on": self._is_enabled,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            }

            response = requests.post(url, json=payload, headers=headers, timeout=10)
            if response.status_code == 200:
                logger.debug("Auto infinite hunt monitor alive ping sent")
            else:
                logger.warning(f"Failed to send monitor ping: {response.status_code}")

        except Exception as exc:
            # Don't crash the monitor if ping fails
            logger.warning(f"Failed to send monitor alive ping: {exc}")

    def _check_and_maybe_auto_start(self) -> None:
        """Check conditions and auto-start infinite hunt if appropriate."""
        # Step 1: Check if auto_infinite_hunt_on is enabled in database
        run_record = self.supabase.get_infinite_run()
        if not run_record:
            self._is_enabled = False
            return

        self._is_enabled = bool(getattr(run_record, "auto_infinite_hunt_on", False))

        if not self._is_enabled:
            logger.debug("auto_infinite_hunt_on is disabled")
            return

        # Step 2: Check if infinite hunt is already running
        metadata_service = get_metadata_service()
        if metadata_service.is_infinite_hunt_running():
            logger.debug("Infinite hunt is already running")
            return

        # Also check database status as backup
        current_status = (run_record.status or "").lower()
        if current_status == "running":
            logger.debug("Infinite hunt status is running in database")
            return

        # Step 3: Prevent rapid restarts
        now = datetime.utcnow()
        time_since_last_start = now - self._last_auto_start_at
        min_interval_seconds = self._min_restart_interval_minutes * 60
        if time_since_last_start.total_seconds() < min_interval_seconds:
            logger.debug(
                f"Auto infinite hunt: Too soon since last auto-start "
                f"({time_since_last_start.total_seconds():.0f}s ago)"
            )
            return

        # Step 4: Validate configuration
        validation_result = self._validate_config(run_record)
        if not validation_result["valid"]:
            logger.warning(
                f"Auto infinite hunt: Config invalid - {validation_result['reason']}"
            )
            return

        # Step 5: All conditions met - auto-start!
        logger.info(
            "Auto infinite hunt: Auto-starting infinite hunt "
            "(30 min check triggered)"
        )
        self._auto_start_infinite_hunt()

    def _validate_config(self, run_record) -> dict:
        """
        Validate that the infinite hunt configuration is ready to start.

        Returns:
            dict with 'valid' (bool) and 'reason' (str) if invalid
        """
        # Check if templates are selected
        template_ids = run_record.selected_ordered_run_template_ids or []
        blocked_ids = run_record.bot_blocked_run_template_ids or []

        # Filter out blocked templates
        available_templates = [
            tid
            for tid in template_ids
            if str(tid) not in [str(bid) for bid in blocked_ids]
        ]

        if not available_templates:
            return {
                "valid": False,
                "reason": "No agent templates selected or all are blocked",
            }

        # Check if semantic instructions are provided
        instructions = (run_record.semantic_instructions or "").strip()
        if not instructions:
            return {"valid": False, "reason": "No job search instructions provided"}

        # All checks passed
        return {"valid": True, "reason": None}

    def _kill_chrome_processes(self) -> None:
        """Kill any existing Chrome processes to prevent profile lock."""
        try:
            system = platform.system().lower()

            if system == "darwin":  # macOS
                subprocess.run(
                    ["pkill", "-9", "chrome"], check=False, capture_output=True
                )
                subprocess.run(
                    ["pkill", "-9", "Google Chrome"],
                    check=False,
                    capture_output=True,
                )
                subprocess.run(
                    ["pkill", "-9", "Chromium"], check=False, capture_output=True
                )
                logger.debug("Killed Chrome processes on macOS")
            elif system == "linux":
                subprocess.run(
                    ["pkill", "-9", "chrome"], check=False, capture_output=True
                )
                subprocess.run(
                    ["pkill", "-9", "chromium"], check=False, capture_output=True
                )
                logger.debug("Killed Chrome processes on Linux")
            elif system == "windows":
                subprocess.run(
                    ["taskkill", "/F", "/IM", "chrome.exe"],
                    check=False,
                    capture_output=True,
                )
                subprocess.run(
                    ["taskkill", "/F", "/IM", "chromium.exe"],
                    check=False,
                    capture_output=True,
                )
                logger.debug("Killed Chrome processes on Windows")

            # Brief pause to allow processes to terminate
            time.sleep(1)

        except Exception as e:
            logger.warning(f"Failed to kill Chrome processes: {e}")
            # Don't fail the start operation if Chrome kill fails

    def _auto_start_infinite_hunt(self) -> None:
        """Start the infinite hunt manager automatically."""
        try:
            # Record the auto-start time
            self._last_auto_start_at = datetime.utcnow()

            # Kill any existing Chrome processes to prevent profile lock
            # (same as frontend does before starting)
            self._kill_chrome_processes()

            # Update database status
            self.supabase.update_infinite_run_state(status="running")

            # Start the infinite hunt manager
            self.infinite_hunt_manager.start()

            logger.info("Auto infinite hunt: Infinite hunt auto-started successfully")

            # Send Mixpanel event for auto-started infinite hunt
            self._send_started_infinite_hunt_event()

        except Exception as exc:
            logger.exception(
                f"Auto infinite hunt: Failed to auto-start infinite hunt: {exc}"
            )
            # Reset to stopped on failure
            try:
                self.supabase.update_infinite_run_state(status="stopped")
            except Exception:
                pass

    def _send_started_infinite_hunt_event(self) -> None:
        """Send a Mixpanel event to track auto-started infinite hunt."""
        try:
            token = jwt_token_manager.get_token()
            if not token:
                logger.debug("No JWT token available for Mixpanel event, skipping")
                return

            url = f"{SERVICE_GATEWAY_URL.rstrip('/')}/api/analytics/mixpanel"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            payload = {
                "event_name": "started_infinite_hunt",
                "properties": {
                    "triggered_by": "auto",
                    "timestamp": datetime.utcnow().isoformat(),
                },
            }

            response = requests.post(url, json=payload, headers=headers, timeout=10)
            if response.status_code == 200:
                logger.debug(
                    "Auto infinite hunt: Mixpanel event sent (triggered_by: auto)"
                )
            else:
                logger.warning(
                    f"Failed to send started_infinite_hunt event: {response.status_code}"
                )

        except Exception as exc:
            # Don't crash the auto-start if Mixpanel event fails
            logger.warning(f"Failed to send started_infinite_hunt event: {exc}")


# Global singleton instance
auto_infinite_hunt_monitor: Optional[AutoInfiniteHuntMonitor] = None


def initialize_auto_infinite_hunt_monitor(
    supabase: SupabaseClient,
    infinite_hunt_manager: "InfiniteHuntManager",
) -> AutoInfiniteHuntMonitor:
    """Initialize and return the global auto infinite hunt monitor instance."""
    global auto_infinite_hunt_monitor
    if auto_infinite_hunt_monitor is None:
        auto_infinite_hunt_monitor = AutoInfiniteHuntMonitor(
            supabase, infinite_hunt_manager
        )
    return auto_infinite_hunt_monitor


def get_auto_infinite_hunt_monitor() -> Optional[AutoInfiniteHuntMonitor]:
    """Get the global auto infinite hunt monitor instance."""
    return auto_infinite_hunt_monitor
