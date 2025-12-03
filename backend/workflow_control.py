#!/usr/bin/env python3
"""
Workflow Control System
@file purpose: Handle stop, pause, resume functionality for workflow execution
"""

import json
import logging
import time
from typing import Any, Dict

from paths import BASE_DIR  # noqa: E402

logger = logging.getLogger(__name__)


class WorkflowController:
    """Controls workflow execution via file-based communication."""

    def __init__(self, workflow_id: str):
        self.workflow_id = workflow_id
        self.control_dir = BASE_DIR / "control" / workflow_id
        self.control_dir.mkdir(parents=True, exist_ok=True)

        # Control files
        self.stop_file = self.control_dir / "stop.signal"
        self.pause_file = self.control_dir / "pause.signal"
        self.status_file = self.control_dir / "status.json"

        # Current state
        self.is_paused = False
        self.is_stopped = False

    def send_stop_signal(self):
        """Send stop signal to workflow (immediate termination)."""
        logger.info(f"Sending stop signal to workflow: {self.workflow_id}")
        self.stop_file.write_text(str(time.time()))
        self._update_status("stop_requested")

    def send_pause_signal(self):
        """Send pause signal to workflow."""
        logger.info(f"Sending pause signal to workflow: {self.workflow_id}")
        self.pause_file.write_text(str(time.time()))
        self._update_status("pause_requested")

    def send_resume_signal(self):
        """Send resume signal to workflow."""
        logger.info(f"Sending resume signal to workflow: {self.workflow_id}")
        if self.pause_file.exists():
            self.pause_file.unlink()
        self._update_status("resume_requested")

    def _update_status(self, status: str):
        """Update workflow status file."""
        status_data = {
            "status": status,
            "timestamp": time.time(),
            "workflow_id": self.workflow_id,
        }
        self.status_file.write_text(json.dumps(status_data, indent=2))

    def cleanup(self):
        """Clean up control files."""
        for file in [self.stop_file, self.pause_file, self.status_file]:
            if file.exists():
                file.unlink()

        # Remove directory if empty
        try:
            self.control_dir.rmdir()
        except OSError:
            pass  # Directory not empty or doesn't exist

    def check_control_signals(self) -> Dict[str, Any]:
        """Check for control signals and return current state."""
        signals = {"should_stop": False, "should_pause": False, "changed": False}

        # Check for stop signal (immediate termination)
        if self.stop_file.exists():
            if not self.is_stopped:
                logger.info(f"Stop signal detected for workflow: {self.workflow_id}")
                self.is_stopped = True
                signals["should_stop"] = True
                signals["changed"] = True
                self._update_status("stopping")

        # Check for pause signal
        elif self.pause_file.exists():
            if not self.is_paused:
                logger.info(f"Pause signal detected for workflow: {self.workflow_id}")
                self.is_paused = True
                signals["should_pause"] = True
                signals["changed"] = True
                self._update_status("paused")

        # Check for resume (pause file removed)
        elif self.is_paused and not self.pause_file.exists():
            logger.info(f"Resume signal detected for workflow: {self.workflow_id}")
            self.is_paused = False
            signals["changed"] = True
            self._update_status("resumed")

        return signals

    def wait_while_paused(self):
        """Wait while workflow is paused."""
        if not self.is_paused:
            return

        logger.info("Workflow paused, waiting for resume signal...")
        self._update_status("paused_waiting")

        while self.pause_file.exists():
            # Check for stop signal while paused
            if self.stop_file.exists():
                logger.info("Stop signal received while paused")
                self.is_stopped = True
                self._update_status("stopped")
                raise WorkflowStoppedException("Workflow stopped while paused")

            time.sleep(0.5)  # Check every 500ms

        logger.info("Workflow resumed")
        self.is_paused = False
        self._update_status("running")


class WorkflowStoppedException(Exception):
    """Exception raised when workflow is stopped."""

    pass


class WorkflowPausedException(Exception):
    """Exception raised when workflow is paused."""

    pass


def create_controller(workflow_id: str) -> WorkflowController:
    """Factory function to create a workflow controller."""
    return WorkflowController(workflow_id)


# CLI interface for external control
if __name__ == "__main__":
    import argparse  # noqa: E402

    parser = argparse.ArgumentParser(description="Control workflow execution")
    parser.add_argument("workflow_id", help="Workflow ID to control")
    parser.add_argument(
        "action",
        choices=["stop", "pause", "resume", "status"],
        help="Action to perform",
    )

    args = parser.parse_args()

    controller = WorkflowController(args.workflow_id)

    if args.action == "stop":
        controller.send_stop_signal()
        print(f"Stop signal sent to workflow: {args.workflow_id}")

    elif args.action == "pause":
        controller.send_pause_signal()
        print(f"Pause signal sent to workflow: {args.workflow_id}")

    elif args.action == "resume":
        controller.send_resume_signal()
        print(f"Resume signal sent to workflow: {args.workflow_id}")

    elif args.action == "status":
        if controller.status_file.exists():
            status_data = json.loads(controller.status_file.read_text())
            print(f"Workflow {args.workflow_id} status: {status_data}")
        else:
            print(f"No status file found for workflow: {args.workflow_id}")
